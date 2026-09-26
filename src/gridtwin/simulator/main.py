"""Fleet-simulator: hosts this instance's Shards of Devices (`SHARD_IDS`), answers Command
batches and per-run resets over NATS request/reply (ADR-002), publishes one Heartbeat batch
per Shard every replay-minute, and reports its own liveness.

Compose runs two replicas: simulator-a hosts shard-0..9, simulator-b shard-10..19.
"""

import asyncio
import json
import logging
import sys

import nats

from gridtwin.fleet.models import Command, ShardReset
from gridtwin.fleet.shard import ShardSimulator
from gridtwin.ledger.db import init_schema, record_heartbeat
from gridtwin.settings import settings
from gridtwin.telemetry.staleness import heartbeat_period_seconds
from gridtwin.transport.nats_transport import (
    CHAOS_DUPLICATES_SUBJECT,
    CHAOS_PARTITION_SUBJECT,
    CHAOS_TELEMETRY_DELAY_SUBJECT,
    pending_limits,
    reset_subject,
    shard_subject,
    telemetry_subject,
)

SERVICE_NAME = "simulator"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


def _dump(models) -> bytes:
    return json.dumps([m.model_dump(mode="json") for m in models]).encode()


async def _serve_shard(nc, shard_id: str, shard: ShardSimulator) -> None:
    async def on_batch(msg) -> None:
        commands = [Command.model_validate(c) for c in json.loads(msg.data.decode())]
        await msg.respond(shard.handle_batch(commands).model_dump_json().encode())

    async def on_reset(msg) -> None:
        reset = ShardReset.model_validate_json(msg.data)
        shard.reset(reset)
        log.info(
            json.dumps(
                {
                    "event": "shard_reset",
                    "run_id": reset.run_id,
                    "shard": shard_id,
                    "devices": len(reset.devices),
                }
            )
        )
        await msg.respond(_dump(shard.heartbeats()))

    limits = pending_limits(settings.nats_pending_msgs_limit, settings.nats_pending_bytes_mb)
    await nc.subscribe(shard_subject(shard_id), cb=on_batch, **limits)
    await nc.subscribe(reset_subject(shard_id), cb=on_reset, **limits)
    log.info("serving shard %s", shard_id)


async def telemetry_loop(nc, shards: dict[str, ShardSimulator]) -> None:
    """One Heartbeat batch per Shard per replay-minute (1 s wall at 60x)."""
    period = heartbeat_period_seconds(
        settings.telemetry_period_replay_seconds, settings.replay_speed
    )
    while True:
        for shard_id, shard in shards.items():
            beats = shard.heartbeats()
            if beats:
                await nc.publish(telemetry_subject(shard_id), _dump(beats))
        await asyncio.sleep(period)


async def liveness_loop(instance_id: str) -> None:
    while True:
        await asyncio.to_thread(record_heartbeat, SERVICE_NAME, instance_id)
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def main() -> None:
    instance_id = settings.instance_id or "simulator-unknown"
    init_schema()
    log.info("connecting to nats at %s", settings.nats_url)
    nc = await nats.connect(settings.nats_url, connect_timeout=3)
    log.info("%s connected: nats, postgres", instance_id)

    shards = {shard_id: ShardSimulator() for shard_id in settings.shard_id_list}
    for shard_id, shard in shards.items():
        await _serve_shard(nc, shard_id, shard)

    async def on_duplicates(msg) -> None:
        active = bool(json.loads(msg.data.decode()).get("active"))
        for shard in shards.values():
            shard.set_duplicates(active)
        log.info(json.dumps({"event": "chaos_duplicates", "active": active}))

    await nc.subscribe(CHAOS_DUPLICATES_SUBJECT, cb=on_duplicates)

    async def on_partition(msg) -> None:
        pct = float(json.loads(msg.data.decode()).get("pct", 0.0))
        dark = 0
        for shard in shards.values():
            shard.set_partition(pct)
            dark += len(shard.partitioned)
        log.info(json.dumps({"event": "chaos_partition", "pct": pct, "devices": dark}))

    async def on_telemetry_delay(msg) -> None:
        body = json.loads(msg.data.decode())
        delay_s = float(body.get("delay_s", 0.0))
        pct = float(body.get("pct", 1.0))
        delayed = 0
        for shard in shards.values():
            shard.set_telemetry_delay(delay_s, pct)
            delayed += len(shard.delayed)
        log.info(
            json.dumps({"event": "chaos_telemetry_delay", "delay_s": delay_s, "devices": delayed})
        )

    await nc.subscribe(CHAOS_PARTITION_SUBJECT, cb=on_partition)
    await nc.subscribe(CHAOS_TELEMETRY_DELAY_SUBJECT, cb=on_telemetry_delay)

    try:
        await asyncio.gather(liveness_loop(instance_id), telemetry_loop(nc, shards))
    finally:
        await nc.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
