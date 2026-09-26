"""`make demo` entry point: starts one ReplayRunWorkflow against the fixture day."""

import asyncio
import logging
import uuid

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from gridtwin.dispatch.workflows import ReplayRunInput, ReplayRunWorkflow
from gridtwin.fleet.models import DeviceState
from gridtwin.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("demo")


def initial_devices() -> list[DeviceState]:
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


async def start_demo_run() -> str:
    run_id = f"demo-{uuid.uuid4().hex[:8]}"
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
    )
    run_input = ReplayRunInput(
        run_id=run_id,
        settlement_point=settings.settlement_point,
        fixture_path=settings.fixture_path,
        shard_id=settings.shard_id,
        devices=initial_devices(),
        discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        charge_threshold_usd=settings.naive_charge_threshold_usd,
        replay_speed=settings.replay_speed,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
    )
    await client.start_workflow(
        ReplayRunWorkflow.run,
        run_input,
        id=f"replay:{run_id}",
        task_queue=settings.task_queue,
    )
    log.info("started run %s", run_id)
    log.info(
        "Temporal UI:  http://localhost:8080/namespaces/%s/workflows", settings.temporal_namespace
    )
    log.info("Dashboard:    http://localhost:3000/live?run=%s", run_id)
    return run_id


if __name__ == "__main__":
    asyncio.run(start_demo_run())
