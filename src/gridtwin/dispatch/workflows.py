"""Temporal workflows: all IO lives in activities (referenced by name, so this module
never imports the psycopg/NATS-backed activity implementations), and workflows use only
Temporal time - no wall clock, no randomness (CLAUDE.md, CONTEXT.md).

`ReplayRunWorkflow` walks a fixture day's Market Intervals and starts one
`MarketIntervalWorkflow` per interval with id `interval:{run_id}:{interval_start}`, so
Temporal rejects (no-ops) a second start of the same interval.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from gridtwin.fleet.disaggregate import disaggregate
from gridtwin.fleet.models import Ack, DeviceState
from gridtwin.ledger.models import IntervalResult
from gridtwin.planner.models import FleetPlan, FleetState
from gridtwin.replay.models import MarketSnapshot

ACTIVITY_TIMEOUT = timedelta(seconds=10)
RETRY_POLICY = RetryPolicy(maximum_attempts=3)
INTERVAL_SECONDS = 900.0
CONTINUE_AS_NEW_EVERY = 48


class ReplayRunInput(BaseModel):
    run_id: str
    settlement_point: str
    fixture_path: str
    shard_id: str
    devices: list[DeviceState]
    discharge_threshold_usd: float
    charge_threshold_usd: float
    replay_speed: float
    dispatch_timeout_seconds: float
    interval_starts: list[datetime] | None = None  # None => load from the fixture
    seeded: bool = False


@workflow.defn
class MarketIntervalWorkflow:
    @workflow.run
    async def run(
        self,
        run_id: str,
        interval_start: datetime,
        settlement_point: str,
        fixture_path: str,
        shard_id: str,
        discharge_threshold_usd: float,
        charge_threshold_usd: float,
        dispatch_timeout_seconds: float,
    ) -> IntervalResult:
        start_time = workflow.now()
        level = "L0"
        snapshot: MarketSnapshot | None = None
        try:
            snapshot = await workflow.execute_activity(
                "get_market_snapshot",
                args=[interval_start, settlement_point, fixture_path],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
                result_type=MarketSnapshot,
            )
        except Exception:
            # Ticket 08 adds the full degradation ladder (L1 cached plan, L2 safe rule,
            # staged recovery). Ticket 02 wires the seam with the L3 Hold fallback.
            level = "L3"

        setpoints: dict[str, float] = {}
        target_mw = 0.0
        achievable_mw = 0.0
        delivered_mw = 0.0
        reserve_violations = 0
        acked_count = 0
        price = 0.0

        if snapshot is not None:
            price = snapshot.rt_price_usd_per_mwh
            fleet_state = await workflow.execute_activity(
                "get_fleet_state",
                args=[run_id],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
                result_type=FleetState,
            )
            plan = await workflow.execute_activity(
                "build_plan",
                args=[fleet_state, snapshot, discharge_threshold_usd, charge_threshold_usd],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
                result_type=FleetPlan,
            )
            target_mw = plan.target_mw
            setpoints = disaggregate(plan.target_mw, fleet_state.devices)
            achievable_mw = sum(setpoints.values())

            acks = await workflow.execute_activity(
                "dispatch_shard",
                args=[run_id, interval_start, shard_id, setpoints, 1, dispatch_timeout_seconds],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                heartbeat_timeout=timedelta(seconds=5),
                retry_policy=RETRY_POLICY,
                result_type=list[Ack],
            )
            delivered_mw = sum(a.delivered_mw for a in acks)
            reserve_violations = sum(1 for a in acks if a.floor_violation)
            acked_count = sum(1 for a in acks if a.applied)

        latency_ms = (workflow.now() - start_time).total_seconds() * 1000
        result = IntervalResult(
            run_id=run_id,
            interval_start=interval_start,
            settlement_point=settlement_point,
            price_usd_per_mwh=price,
            target_mw=target_mw,
            achievable_mw=achievable_mw,
            delivered_mw=delivered_mw,
            level=level,
            dispatched_count=len(setpoints),
            acked_count=acked_count,
            reserve_violations=reserve_violations,
            latency_ms=latency_ms,
        )
        await workflow.execute_activity(
            "record_interval_result",
            args=[result],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        return result


@workflow.defn
class ReplayRunWorkflow:
    @workflow.run
    async def run(self, input: ReplayRunInput) -> None:
        if not input.seeded:
            await workflow.execute_activity(
                "seed_devices",
                args=[input.run_id, input.devices],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )

        interval_starts = input.interval_starts
        if interval_starts is None:
            interval_starts = await workflow.execute_activity(
                "list_interval_starts",
                args=[input.settlement_point, input.fixture_path],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
                result_type=list[datetime],
            )

        seconds_per_interval = INTERVAL_SECONDS / input.replay_speed
        remaining = list(interval_starts)
        processed = 0
        while remaining and processed < CONTINUE_AS_NEW_EVERY:
            interval_start = remaining.pop(0)
            await workflow.execute_child_workflow(
                MarketIntervalWorkflow.run,
                args=[
                    input.run_id,
                    interval_start,
                    input.settlement_point,
                    input.fixture_path,
                    input.shard_id,
                    input.discharge_threshold_usd,
                    input.charge_threshold_usd,
                    input.dispatch_timeout_seconds,
                ],
                id=f"interval:{input.run_id}:{interval_start.isoformat()}",
                # A second start of the same interval id is rejected outright, not just
                # while the first is running: idempotent scheduling (CONTEXT.md).
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            processed += 1
            if remaining:
                await workflow.sleep(seconds_per_interval)

        if remaining:
            workflow.continue_as_new(
                input.model_copy(update={"interval_starts": remaining, "seeded": True})
            )
