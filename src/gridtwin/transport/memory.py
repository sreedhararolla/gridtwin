"""In-memory transport: calls the shard simulator directly, in-process. Used by the
Scenario Runner (Seam A) and unit tests so no NATS container is required."""

from gridtwin.fleet.models import Ack, Command
from gridtwin.fleet.shard import ShardSimulator


class InMemoryTransport:
    def __init__(self, shards: dict[str, ShardSimulator]) -> None:
        self._shards = shards

    async def send_batch(
        self, shard_id: str, commands: list[Command], timeout_seconds: float
    ) -> list[Ack]:
        return self._shards[shard_id].handle_batch(commands)
