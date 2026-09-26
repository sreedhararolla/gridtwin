"""In-memory transport: calls the shard simulators directly, in-process. Used by the
Scenario Runner (Seam A) and unit tests so no NATS container is required.

With a telemetry sink, each shard publishes its Heartbeats after every batch - the
in-process stand-in for the simulator's heartbeat loop plus the telemetry ingester."""

from gridtwin.fleet.models import Ack, Command, Heartbeat, ShardReset
from gridtwin.fleet.shard import ShardSimulator
from gridtwin.telemetry.repo import TelemetryRepo


class InMemoryTransport:
    def __init__(
        self,
        shards: dict[str, ShardSimulator] | None = None,
        telemetry: TelemetryRepo | None = None,
    ) -> None:
        self.shards: dict[str, ShardSimulator] = shards if shards is not None else {}
        self._telemetry = telemetry

    async def reset_shard(self, reset: ShardReset, timeout_seconds: float) -> list[Heartbeat]:
        shard = self.shards.setdefault(reset.shard_id, ShardSimulator())
        shard.reset(reset)
        return shard.heartbeats()

    async def send_batch(
        self, shard_id: str, commands: list[Command], timeout_seconds: float
    ) -> list[Ack]:
        shard = self.shards[shard_id]
        acks = shard.handle_batch(commands)
        if self._telemetry is not None:
            self._telemetry.upsert_heartbeats(shard.heartbeats())
        return acks
