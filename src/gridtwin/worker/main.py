"""Worker stub: connects to Temporal and Postgres, reports liveness via heartbeat.

Later tickets replace the sleep loop with a real Temporal worker polling the
dispatch task queue.
"""

import asyncio
import logging
import sys

from temporalio.client import Client

from gridtwin.ledger.db import init_schema, record_heartbeat
from gridtwin.settings import settings

SERVICE_NAME = "worker"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


async def main() -> None:
    instance_id = settings.instance_id or "worker-unknown"
    init_schema()
    log.info("connecting to temporal at %s", settings.temporal_address)
    await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    log.info("%s connected: temporal, postgres", instance_id)
    while True:
        record_heartbeat(SERVICE_NAME, instance_id)
        await asyncio.sleep(settings.heartbeat_interval_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
