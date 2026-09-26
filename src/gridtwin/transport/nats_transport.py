"""NATS core request/reply transport (ADR-002): one request per shard batch."""

from __future__ import annotations

import json

import nats
from nats.aio.client import Client as NatsClient

from gridtwin.fleet.models import BatchReply, Command, Heartbeat, ShardReset


def shard_subject(shard_id: str) -> str:
    return f"dispatch.{shard_id}"


def reset_subject(shard_id: str) -> str:
    return f"control.{shard_id}.reset"


def telemetry_subject(shard_id: str) -> str:
    return f"telemetry.{shard_id}"


TELEMETRY_WILDCARD = "telemetry.*"
# Broadcast to every simulator: {"active": bool} toggles the duplicate-commands scenario.
CHAOS_DUPLICATES_SUBJECT = "control.chaos.duplicates"
# {"pct": float}: that share of every Shard's Devices goes dark; pct 0 clears it.
CHAOS_PARTITION_SUBJECT = "control.chaos.partition"
# {"delay_s": float, "pct": float}: that share's Heartbeats arrive late; delay_s 0 clears.
CHAOS_TELEMETRY_DELAY_SUBJECT = "control.chaos.telemetry_delay"


def pending_limits(msgs_limit: int, bytes_mb: int) -> dict[str, int]:
    """Backpressure: the bound on one subscription's pending queue. Past it NATS drops
    messages and reports a slow consumer rather than buffering without limit."""
    return {"pending_msgs_limit": msgs_limit, "pending_bytes_limit": bytes_mb * 1024 * 1024}


class NatsTransport:
    def __init__(self, nc: NatsClient) -> None:
        self._nc = nc

    @classmethod
    async def connect(cls, url: str) -> NatsTransport:
        nc = await nats.connect(url)
        return cls(nc)

    async def reset_shard(self, reset: ShardReset, timeout_seconds: float) -> list[Heartbeat]:
        msg = await self._nc.request(
            reset_subject(reset.shard_id), reset.model_dump_json().encode(), timeout=timeout_seconds
        )
        return [Heartbeat.model_validate(h) for h in json.loads(msg.data.decode())]

    async def send_batch(
        self, shard_id: str, commands: list[Command], timeout_seconds: float
    ) -> BatchReply:
        payload = json.dumps([c.model_dump(mode="json") for c in commands]).encode()
        msg = await self._nc.request(shard_subject(shard_id), payload, timeout=timeout_seconds)
        return BatchReply.model_validate_json(msg.data)

    async def _broadcast(self, subject: str, body: dict) -> None:
        """Tell every simulator (fire and forget)."""
        await self._nc.publish(subject, json.dumps(body).encode())
        await self._nc.flush()

    async def set_duplicates(self, active: bool) -> None:
        """Duplicate-commands Chaos Scenario."""
        await self._broadcast(CHAOS_DUPLICATES_SUBJECT, {"active": active})

    async def set_partition(self, pct: float) -> None:
        """Device-partition Chaos Scenario; pct 0 clears it."""
        await self._broadcast(CHAOS_PARTITION_SUBJECT, {"pct": pct})

    async def set_telemetry_delay(self, delay_s: float, pct: float) -> None:
        """Telemetry-delay Chaos Scenario; delay_s 0 clears it."""
        await self._broadcast(CHAOS_TELEMETRY_DELAY_SUBJECT, {"delay_s": delay_s, "pct": pct})

    async def close(self) -> None:
        await self._nc.close()
