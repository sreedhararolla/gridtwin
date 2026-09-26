"""The transport interface: send a Command batch to a shard, get back Acks.

NATS in compose (ADR-002), in-memory for the Scenario Runner and tests.
"""

from typing import Protocol

from gridtwin.fleet.models import Ack, Command


class Transport(Protocol):
    async def send_batch(
        self, shard_id: str, commands: list[Command], timeout_seconds: float
    ) -> list[Ack]: ...
