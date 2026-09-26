"""In-memory transport: calls the shard simulators directly, in-process. Used by the
Scenario Runner (Seam A) and unit tests so no NATS container is required.

With a telemetry sink, each shard publishes its Heartbeats after every batch - the
in-process stand-in for the simulator's heartbeat loop plus the telemetry ingester.

Test hook: `fail_after_partial_send = n` makes the next n batches deliver only their first
half and then raise, as a transport that dies mid-send would. The dispatch activity fails,
Temporal retries it, and the retry re-sends the same keys."""

from gridtwin.fleet.models import BatchReply, Command, Heartbeat, ShardReset
from gridtwin.fleet.shard import ShardSimulator
from gridtwin.telemetry.repo import TelemetryRepo


class PartialSendError(RuntimeError):
    pass


class InMemoryTransport:
    def __init__(
        self,
        shards: dict[str, ShardSimulator] | None = None,
        telemetry: TelemetryRepo | None = None,
        duplicates: bool = False,
    ) -> None:
        self.shards: dict[str, ShardSimulator] = shards if shards is not None else {}
        self._telemetry = telemetry
        self.duplicates = duplicates
        self.fail_after_partial_send = 0

    async def reset_shard(self, reset: ShardReset, timeout_seconds: float) -> list[Heartbeat]:
        shard = self.shards.setdefault(reset.shard_id, ShardSimulator())
        shard.reset(reset)
        shard.set_duplicates(self.duplicates)
        return shard.heartbeats()

    async def send_batch(
        self, shard_id: str, commands: list[Command], timeout_seconds: float
    ) -> BatchReply:
        shard = self.shards[shard_id]
        if self.fail_after_partial_send > 0 and len(commands) > 1:
            self.fail_after_partial_send -= 1
            shard.handle_batch(commands[: len(commands) // 2])
            raise PartialSendError(f"{shard_id}: connection lost after a partial send")
        reply = shard.handle_batch(commands)
        if self._telemetry is not None:
            self._telemetry.upsert_heartbeats(shard.heartbeats())
        return reply
