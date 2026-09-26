"""Seam A: Scenario Reports for 2,000 devices in 20 shards, and interval-id idempotency
(CONTEXT.md: "Interval workflow id ... so Temporal rejects a second start")."""

import pytest
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from gridtwin.dispatch.activities import DispatchActivities
from gridtwin.dispatch.publish import NullPublisher
from gridtwin.dispatch.workflows import (
    MarketIntervalInput,
    MarketIntervalWorkflow,
    ReplayRunWorkflow,
)
from gridtwin.fleet.models import FleetConfig
from gridtwin.ledger.memory_repo import InMemoryLedgerRepo
from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.settings import settings
from gridtwin.telemetry.repo import InMemoryTelemetryRepo
from gridtwin.testing.scenario import run_scenario
from gridtwin.transport.memory import InMemoryTransport

pytestmark = pytest.mark.asyncio

# The real #1 `demo-days` spike day at LZ_HOUSTON (max $1,284.81/MWh), from the cache.
SPIKE_DAY_FIXTURE = "data/fixtures/rtm_spp_lz_houston_2026-01-28.csv"
# Stale threshold for the in-process run: generous, since time-skipping makes replay time
# free but activities still take real milliseconds.
STALE_AFTER_SECONDS = 30.0


def fleet_config(device_count: int = 2000, shard_count: int = 20) -> FleetConfig:
    return settings.fleet_config().model_copy(
        update={"device_count": device_count, "shard_count": shard_count, "seed": 7}
    )


async def run_day(run_id: str, fixture_path: str, fleet: FleetConfig):
    return await run_scenario(
        run_id=run_id,
        fleet=fleet,
        settlement_point=settings.settlement_point,
        fixture_path=fixture_path,
        discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        charge_threshold_usd=settings.naive_charge_threshold_usd,
        replay_speed=settings.replay_speed,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
        stale_after_seconds=STALE_AFTER_SECONDS,
    )


async def test_spike_day_2000_devices_20_shards_meets_slos():
    fixture_rows = load_fixture_day(settings.settlement_point, SPIKE_DAY_FIXTURE)
    outcome = await run_day("scenario-spike-day", SPIKE_DAY_FIXTURE, fleet_config())
    report = outcome.report
    print(report.model_dump_json(indent=2))

    assert report.intervals == len(fixture_rows)
    assert report.reserve_violations == 0
    assert report.within_tolerance_pct >= 95.0
    assert report.max_shards_per_interval == 20
    assert report.min_online_devices == 2000
    # The SoC band drains into the spike: the fleet discharges, so the median falls.
    assert min(r.soc_p50_pct for r in outcome.results) < settings.initial_soc_pct * 100
    assert any(r.delivered_mw > 0 for r in outcome.results)


async def test_fixture_day_scenario_report_meets_slos():
    fixture_rows = load_fixture_day(settings.settlement_point, settings.fixture_path)
    outcome = await run_day("scenario-fixture-day", settings.fixture_path, fleet_config(200, 4))
    assert outcome.report.intervals == len(fixture_rows)
    assert outcome.report.reserve_violations == 0


async def test_second_start_of_same_interval_id_is_rejected():
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
            task_queue="dup-test",
            workflows=[ReplayRunWorkflow, MarketIntervalWorkflow],
            activities=activities.all(),
        ):
            await activities.seed_fleet("dup-run", fleet_config(10, 2), 5.0)
            interval_start = load_fixture_day(settings.settlement_point, settings.fixture_path)[0][
                0
            ]
            workflow_id = f"interval:dup-run:{interval_start.isoformat()}"
            interval_input = MarketIntervalInput(
                run_id="dup-run",
                interval_start=interval_start,
                settlement_point=settings.settlement_point,
                day=None,
                fixture_path=settings.fixture_path,
                discharge_threshold_usd=settings.naive_discharge_threshold_usd,
                charge_threshold_usd=settings.naive_charge_threshold_usd,
                dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
                stale_after_seconds=STALE_AFTER_SECONDS,
                budget_ms=15_000.0,
            )
            handle = await env.client.start_workflow(
                MarketIntervalWorkflow.run,
                interval_input,
                id=workflow_id,
                task_queue="dup-test",
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            await handle.result()

            with pytest.raises(WorkflowAlreadyStartedError):
                await env.client.start_workflow(
                    MarketIntervalWorkflow.run,
                    interval_input,
                    id=workflow_id,
                    task_queue="dup-test",
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
