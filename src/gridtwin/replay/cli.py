"""`make demo [DAY=YYYY-MM-DD]` entry point: starts one ReplayRunWorkflow for any cached
day (or, with no DAY, the checked-in fixture day). The API's `POST /runs` - the Live tab's
day picker - uses the same `start_replay_run`."""

import argparse
import asyncio
import logging
import uuid
from datetime import date

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from gridtwin.dispatch.workflows import WORKFLOW_TASK_TIMEOUT, ReplayRunInput, ReplayRunWorkflow
from gridtwin.marketdata.prices import load_day_prices
from gridtwin.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("demo")


def build_run_input(
    run_id: str,
    day: date | None,
    settlement_point: str,
    strategy: str | None = None,
    storm: bool | None = None,
) -> ReplayRunInput:
    return ReplayRunInput(
        run_id=run_id,
        settlement_point=settlement_point,
        day=day,
        fixture_path=settings.fixture_path,
        fleet=settings.fleet_config(),
        discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        charge_threshold_usd=settings.naive_charge_threshold_usd,
        replay_speed=settings.replay_speed,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
        stale_after_seconds=settings.stale_after_seconds,
        reallocation=settings.reallocation_config(),
        ladder=settings.ladder_config(),
        strategy=strategy or settings.strategy,
        lp=settings.lp_config(),
        storm=settings.storm_config(storm),
    )


async def connect_temporal() -> Client:
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
    )


async def start_replay_run(
    client: Client,
    day: date | None,
    settlement_point: str | None = None,
    strategy: str | None = None,
    storm: bool | None = None,
) -> str:
    point = settlement_point or settings.settlement_point
    # Fail fast (DayNotCached) before starting a workflow that could never load its day.
    load_day_prices(point, day, settings.fixture_path)
    suffix = day.isoformat() if day else "fixture"
    run_id = f"demo-{suffix}-{uuid.uuid4().hex[:6]}"
    await client.start_workflow(
        ReplayRunWorkflow.run,
        build_run_input(run_id, day, point, strategy, storm),
        id=f"replay:{run_id}",
        task_queue=settings.task_queue,
        task_timeout=WORKFLOW_TASK_TIMEOUT,
    )
    return run_id


async def main() -> None:
    parser = argparse.ArgumentParser(prog="gridtwin.replay")
    parser.add_argument("--day", type=date.fromisoformat, default=None)
    parser.add_argument("--settlement-point", default=settings.settlement_point)
    parser.add_argument("--strategy", choices=["naive", "lp", "lp_risk"], default=settings.strategy)
    parser.add_argument(
        "--storm",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Storm mode's Dynamic Reserve Floor (default: STORM_MODE)",
    )
    args = parser.parse_args()

    run_id = await start_replay_run(
        await connect_temporal(), args.day, args.settlement_point, args.strategy, args.storm
    )
    log.info(
        "started run %s: %s at %s, %s strategy, %d devices in %d shards, %sx",
        run_id,
        args.day or "fixture day",
        args.settlement_point,
        args.strategy,
        settings.device_count,
        settings.shard_count,
        settings.replay_speed,
    )
    log.info(
        "Temporal UI:  http://localhost:8080/namespaces/%s/workflows", settings.temporal_namespace
    )
    log.info("Dashboard:    http://localhost:3000/live?run=%s", run_id)


if __name__ == "__main__":
    asyncio.run(main())
