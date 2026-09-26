"""Worker: runs the ReplayRun/MarketInterval Temporal workflows and dispatch activities,
and reports liveness via heartbeat. At least two replicas poll the same task queue
(CONTEXT.md domain invariant)."""

import asyncio
import logging
import sys
from datetime import timedelta

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from gridtwin.dispatch.activities import DispatchActivities
from gridtwin.dispatch.publish import NatsResultPublisher
from gridtwin.dispatch.workflows import MarketIntervalWorkflow, ReplayRunWorkflow
from gridtwin.ledger.db import init_schema, record_heartbeat
from gridtwin.ledger.postgres_repo import PostgresLedgerRepo
from gridtwin.settings import settings
from gridtwin.telemetry.repo import PostgresTelemetryRepo
from gridtwin.transport.nats_transport import NatsTransport

SERVICE_NAME = "worker"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


async def heartbeat_loop(instance_id: str) -> None:
    while True:
        await asyncio.to_thread(record_heartbeat, SERVICE_NAME, instance_id)
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
        repo=PostgresLedgerRepo(),
        telemetry=PostgresTelemetryRepo(),
        transport=transport,
        publisher=publisher,
    )
    log.info("%s connected: temporal, postgres, nats", instance_id)

    worker = Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[ReplayRunWorkflow, MarketIntervalWorkflow],
        activities=activities.all(),
        # 20 shard activities per interval run concurrently across the two workers.
        max_concurrent_activities=64,
        # The chaos controller maps Temporal's worker identity to the container to kill,
        # and Temporal history shows which worker ran each attempt.
        identity=instance_id,
        # A workflow cached on a killed worker moves to the survivor after this, not 10 s.
        sticky_queue_schedule_to_start_timeout=timedelta(seconds=2),
    )
    await asyncio.gather(heartbeat_loop(instance_id), worker.run())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
