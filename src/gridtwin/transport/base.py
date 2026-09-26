"""The transport interface: reset a shard for a run, and send a Command batch to a shard to
get back Acks.

NATS in compose (ADR-002), in-memory for the Scenario Runner and tests.
"""

from typing import Protocol

from gridtwin.fleet.models import Ack, Command, Heartbeat, ShardReset


class Transport(Protocol):
    async def reset_shard(self, reset: ShardReset, timeout_seconds: float) -> list[Heartbeat]:
        """Hand the shard its Devices for a new run; returns its first Heartbeats."""
        ...

    async def send_batch(
        self, shard_id: str, commands: list[Command], timeout_seconds: float
    ) -> list[Ack]: ...
