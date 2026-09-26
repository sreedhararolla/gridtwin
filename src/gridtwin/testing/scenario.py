"""Seam A: the Scenario Runner. Runs a Replay Run in-process - Temporal's time-skipping
test environment, the in-memory transport, telemetry and ledger - and returns a Scenario
Report, the system-level test seam (ADR-005, docs/SPEC.md Testing Decisions)."""

from datetime import date
from statistics import median

from pydantic import BaseModel
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from gridtwin.dispatch.activities import DispatchActivities
from gridtwin.dispatch.publish import NullPublisher
from gridtwin.dispatch.workflows import MarketIntervalWorkflow, ReplayRunInput, ReplayRunWorkflow
from gridtwin.fleet.models import FleetConfig
from gridtwin.ledger.memory_repo import InMemoryLedgerRepo
from gridtwin.ledger.models import IntervalResult
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


class ScenarioResult(BaseModel):
    report: ScenarioReport
    results: list[IntervalResult]


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
) -> ScenarioResult:
    repo = InMemoryLedgerRepo()
    telemetry = InMemoryTelemetryRepo()
    transport = InMemoryTransport(telemetry=telemetry)
    activities = DispatchActivities(
        repo=repo, telemetry=telemetry, transport=transport, publisher=NullPublisher()
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
            )
            handle = await env.client.start_workflow(
                ReplayRunWorkflow.run,
                run_input,
                id=f"replay:{run_id}",
                task_queue=TASK_QUEUE,
            )
            await handle.result()

    results = repo.list_interval_results(run_id)
    return ScenarioResult(report=build_report(results, tolerance_pct), results=results)


def build_report(results: list[IntervalResult], tolerance_pct: float) -> ScenarioReport:
    if not results:
        return ScenarioReport(
            intervals=0,
            within_tolerance_pct=0.0,
            reserve_violations=0,
            value_usd=0.0,
            p99_dispatch_ms=0.0,
        )

    within_tolerance = 0
    for r in results:
        gap = abs(r.achievable_mw - r.delivered_mw)
        tolerance = tolerance_pct * max(abs(r.achievable_mw), 1e-9)
        if gap <= tolerance:
            within_tolerance += 1

    latencies = sorted(r.latency_ms for r in results)
    p99_index = max(int(len(latencies) * 0.99) - 1, 0)
    value_usd = sum(r.delivered_mw * INTERVAL_HOURS * r.price_usd_per_mwh for r in results)

    return ScenarioReport(
        intervals=len(results),
        within_tolerance_pct=100.0 * within_tolerance / len(results),
        reserve_violations=sum(r.reserve_violations for r in results),
        value_usd=value_usd,
        p99_dispatch_ms=latencies[p99_index],
        median_dispatch_ms=median(latencies),
        max_shards_per_interval=max(r.shard_count for r in results),
        min_online_devices=min(r.online_devices for r in results),
    )
