"""Seam A: the Scenario Report for the fixture day, and interval-id idempotency
(CONTEXT.md: "Interval workflow id ... so Temporal rejects a second start")."""

import pytest
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from gridtwin.dispatch.activities import DispatchActivities
from gridtwin.dispatch.publish import NullPublisher
from gridtwin.dispatch.workflows import MarketIntervalWorkflow, ReplayRunWorkflow
from gridtwin.fleet.models import DeviceState
from gridtwin.fleet.shard import ShardSimulator
from gridtwin.ledger.memory_repo import InMemoryLedgerRepo
from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.settings import settings
from gridtwin.testing.scenario import run_scenario
from gridtwin.transport.memory import InMemoryTransport

pytestmark = pytest.mark.asyncio

ACTIVITY_NAMES = [
    "seed_devices",
    "list_interval_starts",
    "get_market_snapshot",
    "get_fleet_state",
    "build_plan",
    "dispatch_shard",
    "record_interval_result",
]


def make_devices() -> list[DeviceState]:
    return [
        DeviceState(
            device_id=device_id,
            soc_pct=settings.initial_soc_pct,
            energy_kwh=settings.device_energy_kwh,
            max_power_kw=settings.device_max_power_kw,
            round_trip_efficiency=settings.device_round_trip_efficiency,
            reserve_floor_pct=settings.reserve_floor_pct,
        )
        for device_id in settings.device_ids
    ]


async def test_fixture_day_scenario_report_meets_slos():
    fixture_rows = load_fixture_day(settings.settlement_point, settings.fixture_path)
    report = await run_scenario(
        run_id="scenario-fixture-day",
        devices=make_devices(),
        settlement_point=settings.settlement_point,
        fixture_path=settings.fixture_path,
        shard_id=settings.shard_id,
        discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        charge_threshold_usd=settings.naive_charge_threshold_usd,
        replay_speed=settings.replay_speed,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
    )
    assert report.intervals == len(fixture_rows)
    assert report.reserve_violations == 0


async def test_second_start_of_same_interval_id_is_rejected():
    repo = InMemoryLedgerRepo()
    devices = make_devices()
    shard_id = settings.shard_id
    transport = InMemoryTransport({shard_id: ShardSimulator(devices)})
    activities = DispatchActivities(repo=repo, transport=transport, publisher=NullPublisher())

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        bound_activities = [getattr(activities, name) for name in ACTIVITY_NAMES]
        async with Worker(
            env.client,
            task_queue="dup-test",
            workflows=[ReplayRunWorkflow, MarketIntervalWorkflow],
            activities=bound_activities,
        ):
            repo.seed_devices("dup-run", devices)
            interval_start = load_fixture_day(settings.settlement_point, settings.fixture_path)[0][
                0
            ]
            workflow_id = f"interval:dup-run:{interval_start.isoformat()}"
            args = [
                "dup-run",
                interval_start,
                settings.settlement_point,
                settings.fixture_path,
                shard_id,
                settings.naive_discharge_threshold_usd,
                settings.naive_charge_threshold_usd,
                settings.dispatch_timeout_seconds,
            ]
            handle = await env.client.start_workflow(
                MarketIntervalWorkflow.run,
                args=args,
                id=workflow_id,
                task_queue="dup-test",
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            await handle.result()

            with pytest.raises(WorkflowAlreadyStartedError):
                await env.client.start_workflow(
                    MarketIntervalWorkflow.run,
                    args=args,
                    id=workflow_id,
                    task_queue="dup-test",
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
