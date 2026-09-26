"""Telemetry ingester: subscribes to every Shard's Heartbeat batches and flushes the latest
state per Device to Postgres once per `TELEMETRY_FLUSH_SECONDS`, in one batched write."""

import asyncio
import json
import logging
import sys

import nats

from gridtwin.fleet.models import Heartbeat
from gridtwin.ledger.db import init_schema, record_heartbeat
from gridtwin.settings import settings
from gridtwin.telemetry.repo import LatestHeartbeats, PostgresTelemetryRepo
from gridtwin.transport.nats_transport import TELEMETRY_WILDCARD

SERVICE_NAME = "telemetry"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


async def flush_loop(buffer: LatestHeartbeats, repo: PostgresTelemetryRepo) -> None:
    while True:
        await asyncio.sleep(settings.telemetry_flush_seconds)
        batch = buffer.drain()
        if batch:
            try:
                await asyncio.to_thread(repo.upsert_heartbeats, batch)
            except Exception:  # noqa: BLE001 - a failed flush must not kill ingestion
                log.exception("telemetry flush failed; re-buffering %d heartbeats", len(batch))
                buffer.add(batch)


async def liveness_loop(instance_id: str) -> None:
    while True:
        await asyncio.to_thread(record_heartbeat, SERVICE_NAME, instance_id)
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def main() -> None:
    instance_id = settings.instance_id or "telemetry-unknown"
    init_schema()
    nc = await nats.connect(settings.nats_url, connect_timeout=3)
    buffer = LatestHeartbeats()

    async def on_heartbeats(msg) -> None:
        buffer.add([Heartbeat.model_validate(h) for h in json.loads(msg.data.decode())])

    await nc.subscribe(TELEMETRY_WILDCARD, cb=on_heartbeats)
    log.info("%s ingesting %s", instance_id, TELEMETRY_WILDCARD)
    try:
        await asyncio.gather(
            liveness_loop(instance_id), flush_loop(buffer, PostgresTelemetryRepo())
        )
    finally:
        await nc.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
