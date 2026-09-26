"""Worker: runs the ReplayRun/MarketInterval Temporal workflows and dispatch activities,
and reports liveness via heartbeat. At least two replicas poll the same task queue
(CONTEXT.md domain invariant)."""

import asyncio
import logging
import sys

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from gridtwin.dispatch.activities import DispatchActivities
from gridtwin.dispatch.publish import NatsResultPublisher
from gridtwin.dispatch.workflows import MarketIntervalWorkflow, ReplayRunWorkflow
from gridtwin.ledger.db import init_schema, record_heartbeat
from gridtwin.ledger.postgres_repo import PostgresLedgerRepo
from gridtwin.settings import settings
from gridtwin.transport.nats_transport import NatsTransport

SERVICE_NAME = "worker"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


async def heartbeat_loop(instance_id: str) -> None:
    while True:
        record_heartbeat(SERVICE_NAME, instance_id)
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def main() -> None:
    instance_id = settings.instance_id or "worker-unknown"
    init_schema()
    log.info("connecting to temporal at %s", settings.temporal_address)
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
    )
    transport = await NatsTransport.connect(settings.nats_url)
    publisher = await NatsResultPublisher.connect(settings.nats_url)
    activities = DispatchActivities(
        repo=PostgresLedgerRepo(), transport=transport, publisher=publisher
    )
    log.info("%s connected: temporal, postgres, nats", instance_id)

    worker = Worker(
        client,
        task_queue=settings.task_queue,
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
    )
    await asyncio.gather(heartbeat_loop(instance_id), worker.run())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
