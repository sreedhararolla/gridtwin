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
from temporalio.exceptions import ActivityError

from gridtwin.dispatch.ladder import (
    FeedGuard,
    FeedStatus,
    LadderConfig,
    cache_plan,
    degraded_target_mw,
    step,
)
from gridtwin.fleet.disaggregate import disaggregate
from gridtwin.fleet.fleet import group_by_shard, soc_band
from gridtwin.fleet.models import FleetConfig
from gridtwin.fleet.reallocate import (
    ReallocationConfig,
    needs_reallocation,
    reallocate,
    reallocation_headroom,
    rerate_achievable,
    with_reserve,
)
from gridtwin.ledger.models import IntervalResult
from gridtwin.planner.models import FleetPlan, FleetState, LpConfig
from gridtwin.replay.breaker import allow, record_failure, record_success
from gridtwin.replay.feed import FeedReading, remember, validate_snapshot
from gridtwin.replay.models import FeedError, MarketSnapshot

# Worker-kill resilience (ticket 05): a short activity lost with its worker is retried on
# the surviving worker after ACTIVITY_TIMEOUT; a lost `dispatch_shard` after
# DISPATCH_HEARTBEAT_TIMEOUT. Both stay well inside a 15 s interval budget at 60x.
ACTIVITY_TIMEOUT = timedelta(seconds=5)
SEED_TIMEOUT = timedelta(seconds=30)
DISPATCH_TIMEOUT = timedelta(seconds=10)
DISPATCH_HEARTBEAT_TIMEOUT = timedelta(seconds=2)
# A workflow task handed to a worker that then dies is retried after this (Temporal's
# default is 10 s, which alone would blow the Recovery Time SLO).
WORKFLOW_TASK_TIMEOUT = timedelta(seconds=2)
RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(milliseconds=200),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)
INTERVAL_SECONDS = 900.0
CONTINUE_AS_NEW_EVERY = 48


class ShardDispatchResult(BaseModel, frozen=True):
    shard_id: str
    dispatched_count: int
    acked_count: int
    delivered_mw: float
    reserve_violations: int
    duplicate_deliveries: int = 0
    duplicate_effects: int = 0
    attempt: int = 1  # the activity attempt that succeeded; > 1 = retried
    # Reallocation inputs: MW per Device that acted, and Devices that sent no Ack at all.
    delivered: dict[str, float] = {}
    unresponsive: list[str] = []


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
    reallocation: ReallocationConfig = ReallocationConfig()
    ladder: LadderConfig = LadderConfig()
    guard: FeedGuard = FeedGuard()  # the ladder state the previous interval left
    strategy: str = "naive"
    lp: LpConfig = LpConfig()


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
    reallocation: ReallocationConfig = ReallocationConfig()
    ladder: LadderConfig = LadderConfig()
    guard: FeedGuard = FeedGuard()  # carried across continue-as-new
    strategy: str = "naive"  # naive | lp | lp_risk
    lp: LpConfig = LpConfig()


class IntervalOutcome(BaseModel, frozen=True):
    result: IntervalResult
    guard: FeedGuard  # the ladder state the next interval starts from


@workflow.defn
class MarketIntervalWorkflow:
    @workflow.run
    async def run(self, input: MarketIntervalInput) -> IntervalOutcome:
        start_time = workflow.now()
        snapshot, guard, feed_status, feed_detail = await self._snapshot(input)
        level = guard.level
        if level != input.guard.level:
            workflow.logger.info(
                "degradation %s -> %s at %s (%s: %s)",
                input.guard.level,
                level,
                input.interval_start.isoformat(),
                feed_status,
                feed_detail or "feed clean",
                extra={"run_id": input.run_id, "interval_start": input.interval_start.isoformat()},
            )

        fleet_state = await workflow.execute_activity(
            "get_fleet_state",
            args=[input.run_id, input.stale_after_seconds, input.interval_start, workflow.now()],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
            result_type=FleetState,
        )
        soc_p10, soc_p50, soc_p90 = soc_band(fleet_state.devices)

        target_mw = 0.0
        achievable_mw = 0.0
        planned_achievable_mw = 0.0
        # The price this interval acted on: the fresh one, else the last valid one.
        price = snapshot.rt_price_usd_per_mwh if snapshot else guard.history.last_price or 0.0
        shard_results: list[ShardDispatchResult] = []
        unresponsive: set[str] = set()
        rounds = 0
        reallocated_mw = 0.0
        reallocated_devices: set[str] = set()

        # The planner needs aggregate headroom only (2,000 devices stay out of it), less
        # the reserve that gives Reallocation somewhere to go.
        planning_state = with_reserve(fleet_state, input.reallocation.reserve_pct)
        target: float | None
        plan: FleetPlan | None = None
        if level == "L0" and snapshot is not None:
            plan = await workflow.execute_activity(
                "build_plan",
                args=[
                    planning_state,
                    snapshot,
                    input.strategy,
                    input.discharge_threshold_usd,
                    input.charge_threshold_usd,
                    input.lp,
                    input.fixture_path,
                ],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
                result_type=FleetPlan,
            )
            target = plan.target_mw
            guard = cache_plan(guard, input.interval_start, target, input.ladder)
        else:
            # Below L0 nothing reads this interval's snapshot: L1 replays the cached plan,
            # L2 applies the Safe Rule to the last valid price, L3 Holds (None).
            target = degraded_target_mw(
                level, guard, planning_state.discharge_headroom_mw, input.discharge_threshold_usd
            )

        if target is not None:
            target_mw = target
            setpoints = disaggregate(target_mw, fleet_state.devices)
            planned_achievable_mw = achievable_mw = sum(setpoints.values())
            shard_results = await self._dispatch(input, setpoints, fleet_state, seq=1)

            # Devices that never answered are dark: re-rate the Achievable Target without
            # them, then chase any Shortfall on the Devices that still have Headroom.
            unresponsive = {d for r in shard_results for d in r.unresponsive}
            if unresponsive:
                achievable_mw = rerate_achievable(target_mw, fleet_state.devices, unresponsive)
            delivered = _merge_delivered({}, shard_results)
            discharge = target_mw >= 0
            config = input.reallocation
            deadline = start_time + timedelta(milliseconds=input.budget_ms * config.deadline_pct)
            while (
                rounds < config.max_rounds
                and workflow.now() < deadline
                and needs_reallocation(
                    achievable_mw,
                    sum(r.delivered_mw for r in shard_results),
                    config.tolerance_pct,
                )
            ):
                shortfall = achievable_mw - sum(r.delivered_mw for r in shard_results)
                extra = reallocate(
                    shortfall, reallocation_headroom(fleet_state.devices, delivered, discharge)
                )
                if not extra:
                    break
                rounds += 1
                reallocated_mw += abs(sum(extra.values()))
                reallocated_devices.update(extra)
                # A seq+1 Setpoint is the Device's new total for the interval.
                totals = {d: delivered[d] + mw for d, mw in extra.items()}
                round_results = await self._dispatch(input, totals, fleet_state, seq=rounds + 1)
                shard_results.extend(round_results)
                delivered = _merge_delivered(delivered, round_results)
                for r in round_results:
                    # Went dark mid-interval: keep what it delivered, never ask it again.
                    for device_id in r.unresponsive:
                        delivered.pop(device_id, None)

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
            duplicate_deliveries=sum(r.duplicate_deliveries for r in shard_results),
            duplicate_effects=sum(r.duplicate_effects for r in shard_results),
            retried_dispatches=sum(1 for r in shard_results if r.attempt > 1),
            latency_ms=latency_ms,
            budget_ms=input.budget_ms,
            online_devices=len(fleet_state.devices),
            shard_count=len({r.shard_id for r in shard_results}),
            soc_p10_pct=soc_p10,
            soc_p50_pct=soc_p50,
            soc_p90_pct=soc_p90,
            planned_achievable_mw=planned_achievable_mw,
            stale_devices=fleet_state.stale_devices,
            unresponsive_devices=len(unresponsive),
            reallocation_rounds=rounds,
            reallocated_mw=reallocated_mw,
            reallocated_devices=len(reallocated_devices),
            feed_status=feed_status,
            feed_detail=feed_detail,
            # Below L0 the ladder, not a Strategy, set the target: no plan to audit.
            strategy=plan.strategy if plan else "",
            forecast_source=plan.forecast_source if plan else "",
            plan_mw=plan.horizon_mw if plan else [],
        )
        await workflow.execute_activity(
            "record_interval_result",
            args=[result],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        return IntervalOutcome(result=result, guard=guard)

    async def _snapshot(
        self, input: MarketIntervalInput
    ) -> tuple[MarketSnapshot | None, FeedGuard, FeedStatus, str]:
        """Read the feed through the circuit breaker and the validator, then step the
        Degradation Ladder. Returns the valid snapshot (or None) and the new guard."""
        config = input.ladder
        guard = input.guard
        breaker = allow(guard.breaker, input.interval_start, config.breaker)
        snapshot: MarketSnapshot | None = None
        status: FeedStatus = "ok"
        detail = ""
        if breaker.status == "open":
            status, detail = "circuit-open", "feed circuit open: not called this interval"
        else:
            try:
                reading = await workflow.execute_activity(
                    "read_feed",
                    args=[
                        input.run_id,
                        input.interval_start,
                        input.settlement_point,
                        input.day,
                        input.fixture_path,
                    ],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=RETRY_POLICY,
                    result_type=FeedReading,
                )
                snapshot = validate_snapshot(reading, guard.history, config.validator)
            except ActivityError as err:
                status, detail = "outage", str(err.cause or err)
            except FeedError as err:
                status, detail = "rejected", str(err)
            if snapshot is None:
                breaker = record_failure(breaker, input.interval_start, config.breaker)
            else:
                breaker = record_success(breaker)

        history = guard.history
        if snapshot is not None:
            history = remember(history, snapshot, config.validator)
        guard = step(
            guard.model_copy(update={"breaker": breaker, "history": history}),
            input.interval_start,
            snapshot is not None,
            config,
        )
        return snapshot, guard, status, detail

    async def _dispatch(
        self,
        input: MarketIntervalInput,
        setpoints: dict[str, float],
        fleet_state: FleetState,
        seq: int,
    ) -> list[ShardDispatchResult]:
        """One Command batch per Shard, all concurrently."""
        batches = group_by_shard(setpoints, fleet_state.devices)
        return list(
            await asyncio.gather(
                *(
                    workflow.execute_activity(
                        "dispatch_shard",
                        args=[
                            input.run_id,
                            input.interval_start,
                            shard_id,
                            batch,
                            seq,
                            input.dispatch_timeout_seconds,
                        ],
                        start_to_close_timeout=DISPATCH_TIMEOUT,
                        heartbeat_timeout=DISPATCH_HEARTBEAT_TIMEOUT,
                        retry_policy=RETRY_POLICY,
                        result_type=ShardDispatchResult,
                        activity_id=f"dispatch:{shard_id}"
                        if seq == 1
                        else f"dispatch:{shard_id}:{seq}",
                    )
                    for shard_id, batch in sorted(batches.items())
                )
            )
        )


def _merge_delivered(
    delivered: dict[str, float], results: list[ShardDispatchResult]
) -> dict[str, float]:
    """Running MW per Device across this interval's seqs (Devices that acted only)."""
    merged = dict(delivered)
    for r in results:
        for device_id, mw in r.delivered.items():
            merged[device_id] = merged.get(device_id, 0.0) + mw
    return merged


@workflow.defn
class ReplayRunWorkflow:
    @workflow.run
    async def run(self, input: ReplayRunInput) -> None:
        if not input.seeded:
            await workflow.execute_activity(
                "seed_fleet",
                args=[input.run_id, input.fleet, input.dispatch_timeout_seconds],
                start_to_close_timeout=SEED_TIMEOUT,
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
        guard = input.guard
        while remaining and processed < CONTINUE_AS_NEW_EVERY:
            interval_start = remaining.pop(0)
            started = workflow.now()
            outcome = await workflow.execute_child_workflow(
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
                    reallocation=input.reallocation,
                    ladder=input.ladder,
                    guard=guard,
                    strategy=input.strategy,
                    lp=input.lp,
                ),
                id=f"interval:{input.run_id}:{interval_start.isoformat()}",
                # A second start of the same interval id is rejected outright, not just
                # while the first is running: idempotent scheduling (CONTEXT.md).
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                task_timeout=WORKFLOW_TASK_TIMEOUT,
            )
            guard = outcome.guard
            processed += 1
            if remaining:
                # Hold the replay cadence: the interval's dispatch time comes out of its
                # wall budget instead of being added on top of it.
                remaining_budget = seconds_per_interval - (workflow.now() - started).total_seconds()
                if remaining_budget > 0:
                    await workflow.sleep(remaining_budget)

        if remaining:
            workflow.continue_as_new(
                input.model_copy(
                    update={"interval_starts": remaining, "seeded": True, "guard": guard}
                )
            )
