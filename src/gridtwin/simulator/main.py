"""Fleet-simulator stub: connects to NATS and Postgres, reports liveness via heartbeat.

Later tickets replace this with the shard simulator that answers dispatch
command batches over NATS request/reply.
"""

import asyncio
import logging
import sys

import nats

from gridtwin.ledger.db import init_schema, record_heartbeat
from gridtwin.settings import settings

SERVICE_NAME = "simulator"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


async def main() -> None:
    instance_id = settings.instance_id or "simulator-unknown"
    init_schema()
    log.info("connecting to nats at %s", settings.nats_url)
    nc = await nats.connect(settings.nats_url, connect_timeout=3)
    log.info("%s connected: nats, postgres", instance_id)
    try:
        while True:
            record_heartbeat(SERVICE_NAME, instance_id)
            await asyncio.sleep(settings.heartbeat_interval_seconds)
    finally:
        await nc.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
