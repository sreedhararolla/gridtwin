"""Seam A: the Scenario Runner. Runs a Replay Run in-process - Temporal's time-skipping
test environment, the in-memory transport, an in-memory ledger - and returns a Scenario
Report, the system-level test seam (ADR-005, docs/SPEC.md Testing Decisions)."""

from pydantic import BaseModel
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from gridtwin.dispatch.activities import DispatchActivities
from gridtwin.dispatch.publish import NullPublisher
from gridtwin.dispatch.workflows import MarketIntervalWorkflow, ReplayRunInput, ReplayRunWorkflow
from gridtwin.fleet.models import DeviceState
from gridtwin.fleet.shard import ShardSimulator
from gridtwin.ledger.memory_repo import InMemoryLedgerRepo
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


async def run_scenario(
    run_id: str,
    devices: list[DeviceState],
    settlement_point: str,
    fixture_path: str,
    shard_id: str,
    discharge_threshold_usd: float,
    charge_threshold_usd: float,
    replay_speed: float,
    dispatch_timeout_seconds: float,
    tolerance_pct: float = 0.05,
) -> ScenarioReport:
    repo = InMemoryLedgerRepo()
    shard = ShardSimulator(devices)
    transport = InMemoryTransport({shard_id: shard})
    activities = DispatchActivities(repo=repo, transport=transport, publisher=NullPublisher())

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ReplayRunWorkflow, MarketIntervalWorkflow],
            activities=[
                activities.seed_devices,
                activities.list_interval_starts,
                activities.get_market_snapshot,
                activities.get_fleet_state,
                activities.build_plan,
                activities.dispatch_shard,
                activities.record_interval_result,
            ],
        ):
            run_input = ReplayRunInput(
                run_id=run_id,
                settlement_point=settlement_point,
                fixture_path=fixture_path,
                shard_id=shard_id,
                devices=devices,
                discharge_threshold_usd=discharge_threshold_usd,
                charge_threshold_usd=charge_threshold_usd,
                replay_speed=replay_speed,
                dispatch_timeout_seconds=dispatch_timeout_seconds,
            )
            handle = await env.client.start_workflow(
                ReplayRunWorkflow.run,
                run_input,
                id=f"replay:{run_id}",
                task_queue=TASK_QUEUE,
            )
            await handle.result()

    return _build_report(repo, run_id, tolerance_pct)


def _build_report(repo: InMemoryLedgerRepo, run_id: str, tolerance_pct: float) -> ScenarioReport:
    results = repo.list_interval_results(run_id)
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
    )
