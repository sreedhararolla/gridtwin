"""Seam A: the Scenario Runner. Runs a Replay Run in-process - Temporal's time-skipping
test environment, the in-memory transport, telemetry and ledger - and returns a Scenario
Report, the system-level test seam (ADR-005, docs/SPEC.md Testing Decisions)."""

from datetime import date, datetime
from statistics import median

from pydantic import BaseModel
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from gridtwin.chaos.models import FEED_SCENARIOS
from gridtwin.chaos.script import ChaosScript, ChaosStep, select_window
from gridtwin.chaos.slo import within_tolerance_pct
from gridtwin.dispatch.activities import DispatchActivities
from gridtwin.dispatch.ladder import LEVELS, DegradationEvent, LadderConfig, degradation_timeline
from gridtwin.dispatch.publish import NullPublisher
from gridtwin.dispatch.workflows import MarketIntervalWorkflow, ReplayRunInput, ReplayRunWorkflow
from gridtwin.fleet.models import FleetConfig
from gridtwin.fleet.reallocate import ReallocationConfig
from gridtwin.ledger.memory_repo import InMemoryLedgerRepo
from gridtwin.ledger.models import IntervalResult, LedgerIntervalSummary
from gridtwin.marketdata.prices import load_day_prices
from gridtwin.telemetry.repo import InMemoryTelemetryRepo
from gridtwin.transport.memory import InMemoryTransport

TASK_QUEUE = "scenario-runner"
INTERVAL_HOURS = 0.25


class ScenarioReport(BaseModel):
    intervals: int
    within_tolerance_pct: float
    reserve_violations: int
    duplicate_deliveries: int = 0
    duplicate_effects: int = 0
    max_recovery_s: float = 0.0
    degradation_events: int = 0
    value_usd: float
    p99_dispatch_ms: float
    median_dispatch_ms: float = 0.0
    max_shards_per_interval: int = 0
    min_online_devices: int = 0
    # Chaos runs (compose mode, `make chaos`): faults injected and the evidence they left.
    missed_intervals: int = 0
    chaos_events: int = 0
    retried_dispatches: int = 0
    # Staleness and Reallocation (ticket 07).
    max_stale_devices: int = 0
    unresponsive_devices: int = 0  # summed over intervals
    reallocation_rounds: int = 0  # summed over intervals
    reallocated_mw: float = 0.0  # summed over intervals
    # Degradation Ladder (ticket 08): transitions and rejected snapshots, in order.
    # `degradation_events` counts them.
    degradation_timeline: list[DegradationEvent] = []
    worst_level: str = "L0"


class ScenarioResult(BaseModel):
    report: ScenarioReport
    results: list[IntervalResult]
    ledger: list[LedgerIntervalSummary] = []
    ledger_rows: int = 0  # Commands in the ledger: one row per Idempotency Key
    chaos_steps: list[tuple[int, str, str]] = []  # (window index, scenario, apply|clear)


class InProcessChaos:
    """The in-process stand-in for the simulators' heartbeat loop and the chaos controller.

    Called just before each interval's Fleet State is read: every live Device heartbeats
    (on the workflow's clock), then any Chaos Script step due at this interval is applied or
    cleared. A step therefore lands *after* the interval's telemetry and before its dispatch,
    the worst case for a partition: Devices that looked online get Commands they never see.
    """

    def __init__(
        self,
        transport: InMemoryTransport,
        steps: list[ChaosStep],
        window: list[datetime],
        partition_pct: float,
        delay_s: float,
        delay_pct: float,
    ) -> None:
        self._transport = transport
        self._index = {interval_start: i for i, interval_start in enumerate(window)}
        self._steps = steps
        self._partition_pct = partition_pct
        self._delay_s = delay_s
        self._delay_pct = delay_pct
        self.events: list[tuple[int, str, str]] = []  # (window index, scenario, apply|clear)

    def __call__(self, interval_start: datetime, now: datetime) -> None:
        self._transport.tick(now)
        k = self._index.get(interval_start)
        if k is None:
            return
        for step in self._steps:
            if step.at_interval == k:
                self._set(step, active=True)
                self.events.append((k, step.apply, "apply"))
            elif step.at_interval + step.for_intervals == k:
                self._set(step, active=False)
                self.events.append((k, step.apply, "clear"))

    def feed_faults(self, _run_id: str, interval_start: datetime) -> set[str]:
        """The feed Chaos Scenarios on at this interval: the replay feed's view of the
        script (feed faults need no transport, so they are looked up, not switched)."""
        k = self._index.get(interval_start)
        if k is None:
            return set()
        return {
            step.apply
            for step in self._steps
            if step.apply in FEED_SCENARIOS
            and step.at_interval <= k < step.at_interval + step.for_intervals
        }

    def _set(self, step: ChaosStep, active: bool) -> None:
        if step.apply in FEED_SCENARIOS:
            return  # read by `feed_faults` instead
        for shard in self._transport.shards.values():
            if step.apply == "partition":
                shard.set_partition((step.pct or self._partition_pct) if active else 0.0)
            elif step.apply == "telemetry-delay":
                delay_s = step.delay_s or self._delay_s
                shard.set_telemetry_delay(delay_s if active else 0.0, step.pct or self._delay_pct)
            elif step.apply == "duplicate-commands":
                shard.set_duplicates(active)
            else:
                raise ValueError(f"{step.apply} needs compose mode (make test-e2e)")


async def run_scenario(
    run_id: str,
    fleet: FleetConfig,
    settlement_point: str,
    fixture_path: str,
    discharge_threshold_usd: float,
    charge_threshold_usd: float,
    replay_speed: float,
    dispatch_timeout_seconds: float,
    stale_after_seconds: float,
    day: date | None = None,
    tolerance_pct: float = 0.05,
    duplicate_commands: bool = False,
    partial_send_failures: int = 0,
    script: ChaosScript | None = None,
    reallocation: ReallocationConfig | None = None,
    partition_pct: float = 0.2,
    telemetry_delay_s: float = 10.0,
    telemetry_delay_pct: float = 0.3,
    ladder: LadderConfig | None = None,
    strategy: str = "naive",
) -> ScenarioResult:
    """`duplicate_commands` runs the whole replay under the duplicate-commands Chaos
    Scenario; `partial_send_failures` = n makes the first n Shard batches fail after a
    partial send, forcing Temporal to retry those dispatches. `script` replays a Chaos
    Script's window and steps in-process (the same scenarios/*.yaml `make chaos` runs)."""
    repo = InMemoryLedgerRepo()
    telemetry = InMemoryTelemetryRepo()
    transport = InMemoryTransport(telemetry=telemetry, duplicates=duplicate_commands)
    transport.fail_after_partial_send = partial_send_failures
    window: list[datetime] | None = None
    if script is not None:
        rows = load_day_prices(settlement_point, day, fixture_path)
        window = select_window([interval_start for interval_start, _ in rows], script.window)
    chaos = InProcessChaos(
        transport,
        script.steps if script else [],
        window or [],
        partition_pct,
        telemetry_delay_s,
        telemetry_delay_pct,
    )
    activities = DispatchActivities(
        repo=repo,
        telemetry=telemetry,
        transport=transport,
        publisher=NullPublisher(),
        on_fleet_state=chaos,
        feed_faults=chaos.feed_faults,
    )

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ReplayRunWorkflow, MarketIntervalWorkflow],
            activities=activities.all(),
        ):
            run_input = ReplayRunInput(
                run_id=run_id,
                settlement_point=settlement_point,
                day=day,
                fixture_path=fixture_path,
                fleet=fleet,
                discharge_threshold_usd=discharge_threshold_usd,
                charge_threshold_usd=charge_threshold_usd,
                replay_speed=replay_speed,
                dispatch_timeout_seconds=dispatch_timeout_seconds,
                stale_after_seconds=stale_after_seconds,
                interval_starts=window,
                reallocation=reallocation or ReallocationConfig(tolerance_pct=tolerance_pct),
                ladder=ladder or LadderConfig(),
                strategy=strategy,
            )
            handle = await env.client.start_workflow(
                ReplayRunWorkflow.run,
                run_input,
                id=f"replay:{run_id}",
                task_queue=TASK_QUEUE,
            )
            await handle.result()

    results = repo.list_interval_results(run_id)
    return ScenarioResult(
        report=build_report(results, tolerance_pct),
        results=results,
        ledger=repo.ledger_summary(run_id),
        ledger_rows=repo.command_counts(run_id)[0],
        chaos_steps=chaos.events,
    )


def build_report(results: list[IntervalResult], tolerance_pct: float) -> ScenarioReport:
    if not results:
        return ScenarioReport(
            intervals=0,
            within_tolerance_pct=0.0,
            reserve_violations=0,
            value_usd=0.0,
            p99_dispatch_ms=0.0,
        )

    latencies = sorted(r.latency_ms for r in results)
    timeline = degradation_timeline(results)
    p99_index = max(int(len(latencies) * 0.99) - 1, 0)
    value_usd = sum(r.delivered_mw * INTERVAL_HOURS * r.price_usd_per_mwh for r in results)

    return ScenarioReport(
        intervals=len(results),
        within_tolerance_pct=within_tolerance_pct(results, tolerance_pct),
        reserve_violations=sum(r.reserve_violations for r in results),
        duplicate_deliveries=sum(r.duplicate_deliveries for r in results),
        duplicate_effects=sum(r.duplicate_effects for r in results),
        retried_dispatches=sum(r.retried_dispatches for r in results),
        value_usd=value_usd,
        p99_dispatch_ms=latencies[p99_index],
        median_dispatch_ms=median(latencies),
        max_shards_per_interval=max(r.shard_count for r in results),
        min_online_devices=min(r.online_devices for r in results),
        max_stale_devices=max(r.stale_devices for r in results),
        unresponsive_devices=sum(r.unresponsive_devices for r in results),
        reallocation_rounds=sum(r.reallocation_rounds for r in results),
        reallocated_mw=sum(r.reallocated_mw for r in results),
        degradation_events=len(timeline),
        degradation_timeline=timeline,
        worst_level=max((r.level for r in results), key=LEVELS.index),
    )
