"""Fleet-simulator: hosts this instance's shard(s) of Devices, answers Command batches
over NATS request/reply (ADR-002), and reports liveness via heartbeat.

Ticket 02 runs a single shard of 10 devices; ticket 04 spreads many shards across
simulator replicas via `SHARD_IDS`.
"""

import asyncio
import json
import logging
import sys

import nats

from gridtwin.fleet.models import Ack, Command, DeviceState
from gridtwin.fleet.shard import ShardSimulator
from gridtwin.ledger.db import init_schema, record_heartbeat
from gridtwin.settings import settings
from gridtwin.transport.nats_transport import shard_subject

SERVICE_NAME = "simulator"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


def _initial_devices() -> list[DeviceState]:
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


async def _serve_shard(nc, shard_id: str, shard: ShardSimulator) -> None:
    async def handler(msg) -> None:
        commands = [Command.model_validate(c) for c in json.loads(msg.data.decode())]
        acks: list[Ack] = shard.handle_batch(commands)
        await msg.respond(json.dumps([a.model_dump(mode="json") for a in acks]).encode())

    await nc.subscribe(shard_subject(shard_id), cb=handler)
    log.info("serving shard %s (%d devices)", shard_id, len(shard.snapshot()))


async def heartbeat_loop(instance_id: str) -> None:
    while True:
        record_heartbeat(SERVICE_NAME, instance_id)
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def main() -> None:
    instance_id = settings.instance_id or "simulator-unknown"
    init_schema()
    log.info("connecting to nats at %s", settings.nats_url)
    nc = await nats.connect(settings.nats_url, connect_timeout=3)
    log.info("%s connected: nats, postgres", instance_id)

    devices = _initial_devices()
    for shard_id in settings.shard_id_list:
        await _serve_shard(nc, shard_id, ShardSimulator(devices))

    try:
        await heartbeat_loop(instance_id)
    finally:
        await nc.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
