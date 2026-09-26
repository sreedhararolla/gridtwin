"""Temporal workflows: all IO lives in activities (referenced by name, so this module
never imports the psycopg/NATS-backed activity implementations), and workflows use only
Temporal time - no wall clock, no randomness (CLAUDE.md, CONTEXT.md).

`ReplayRunWorkflow` walks a replay day's Market Intervals and starts one
`MarketIntervalWorkflow` per interval with id `interval:{run_id}:{interval_start}`, so
Temporal rejects (no-ops) a second start of the same interval. Each interval fans out one
`dispatch_shard` activity per Shard, all concurrently.
"""

import asyncio
from datetime import date, datetime, timedelta

from pydantic import BaseModel
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from gridtwin.fleet.disaggregate import disaggregate
from gridtwin.fleet.fleet import group_by_shard, soc_band
from gridtwin.fleet.models import FleetConfig
from gridtwin.ledger.models import IntervalResult
from gridtwin.planner.models import FleetPlan, FleetState
from gridtwin.replay.models import MarketSnapshot

ACTIVITY_TIMEOUT = timedelta(seconds=10)
RETRY_POLICY = RetryPolicy(maximum_attempts=3)
INTERVAL_SECONDS = 900.0
CONTINUE_AS_NEW_EVERY = 48


class ShardDispatchResult(BaseModel, frozen=True):
    shard_id: str
    dispatched_count: int
    acked_count: int
    delivered_mw: float
    reserve_violations: int


class MarketIntervalInput(BaseModel, frozen=True):
    run_id: str
    interval_start: datetime
    settlement_point: str
    day: date | None
    fixture_path: str
    discharge_threshold_usd: float
    charge_threshold_usd: float
    dispatch_timeout_seconds: float
    stale_after_seconds: float
    budget_ms: float


class ReplayRunInput(BaseModel):
    run_id: str
    settlement_point: str
    day: date | None = None  # None => the checked-in fixture day (tests, CI)
    fixture_path: str
    fleet: FleetConfig
    discharge_threshold_usd: float
    charge_threshold_usd: float
    replay_speed: float
    dispatch_timeout_seconds: float
    stale_after_seconds: float
    interval_starts: list[datetime] | None = None  # None => load from the replay day
    seeded: bool = False


@workflow.defn
class MarketIntervalWorkflow:
    @workflow.run
    async def run(self, input: MarketIntervalInput) -> IntervalResult:
        start_time = workflow.now()
        level = "L0"
        snapshot: MarketSnapshot | None = None
        try:
            snapshot = await workflow.execute_activity(
                "get_market_snapshot",
                args=[input.interval_start, input.settlement_point, input.day, input.fixture_path],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
                result_type=MarketSnapshot,
            )
        except Exception:
            # Ticket 08 adds the full degradation ladder (L1 cached plan, L2 safe rule,
            # staged recovery). Ticket 02 wires the seam with the L3 Hold fallback.
            level = "L3"

        fleet_state = await workflow.execute_activity(
            "get_fleet_state",
            args=[input.run_id, input.stale_after_seconds],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
            result_type=FleetState,
        )
        soc_p10, soc_p50, soc_p90 = soc_band(fleet_state.devices)

        target_mw = 0.0
        achievable_mw = 0.0
        price = 0.0
        shard_results: list[ShardDispatchResult] = []

        if snapshot is not None:
            price = snapshot.rt_price_usd_per_mwh
            plan = await workflow.execute_activity(
                "build_plan",
                # The planner needs aggregate headroom only; keep 2,000 devices out of it.
                args=[
                    fleet_state.model_copy(update={"devices": []}),
                    snapshot,
                    input.discharge_threshold_usd,
                    input.charge_threshold_usd,
                ],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
                result_type=FleetPlan,
            )
            target_mw = plan.target_mw
            setpoints = disaggregate(plan.target_mw, fleet_state.devices)
            achievable_mw = sum(setpoints.values())
            batches = group_by_shard(setpoints, fleet_state.devices)

            shard_results = list(
                await asyncio.gather(
                    *(
                        workflow.execute_activity(
                            "dispatch_shard",
                            args=[
                                input.run_id,
                                input.interval_start,
                                shard_id,
                                batch,
                                1,
                                input.dispatch_timeout_seconds,
                            ],
                            start_to_close_timeout=ACTIVITY_TIMEOUT,
                            heartbeat_timeout=timedelta(seconds=5),
                            retry_policy=RETRY_POLICY,
                            result_type=ShardDispatchResult,
                            activity_id=f"dispatch:{shard_id}",
                        )
                        for shard_id, batch in sorted(batches.items())
                    )
                )
            )

        latency_ms = (workflow.now() - start_time).total_seconds() * 1000
        result = IntervalResult(
            run_id=input.run_id,
            interval_start=input.interval_start,
            settlement_point=input.settlement_point,
            price_usd_per_mwh=price,
            target_mw=target_mw,
            achievable_mw=achievable_mw,
            delivered_mw=sum(r.delivered_mw for r in shard_results),
            level=level,
            dispatched_count=sum(r.dispatched_count for r in shard_results),
            acked_count=sum(r.acked_count for r in shard_results),
            reserve_violations=sum(r.reserve_violations for r in shard_results),
            latency_ms=latency_ms,
            budget_ms=input.budget_ms,
            online_devices=len(fleet_state.devices),
            shard_count=len(shard_results),
            soc_p10_pct=soc_p10,
            soc_p50_pct=soc_p50,
            soc_p90_pct=soc_p90,
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
                "seed_fleet",
                args=[input.run_id, input.fleet, input.dispatch_timeout_seconds],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )

        interval_starts = input.interval_starts
        if interval_starts is None:
            interval_starts = await workflow.execute_activity(
                "list_interval_starts",
                args=[input.settlement_point, input.day, input.fixture_path],
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
                MarketIntervalInput(
                    run_id=input.run_id,
                    interval_start=interval_start,
                    settlement_point=input.settlement_point,
                    day=input.day,
                    fixture_path=input.fixture_path,
                    discharge_threshold_usd=input.discharge_threshold_usd,
                    charge_threshold_usd=input.charge_threshold_usd,
                    dispatch_timeout_seconds=input.dispatch_timeout_seconds,
                    stale_after_seconds=input.stale_after_seconds,
                    budget_ms=seconds_per_interval * 1000,
                ),
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
