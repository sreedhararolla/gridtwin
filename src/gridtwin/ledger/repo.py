"""The ledger's interface: idempotent upsert by Idempotency Key, plus results (CONTEXT.md).

`PostgresLedgerRepo` backs the real worker; `InMemoryLedgerRepo` backs the Scenario
Runner (Seam A) so tests need no Postgres container. Writes are batched per shard: one
round trip per Command batch, not one per Device.
"""

from typing import Protocol

from gridtwin.fleet.models import Ack, Command, DeviceState
from gridtwin.ledger.models import IntervalResult, LedgerIntervalSummary


class LedgerRepo(Protocol):
    def seed_devices(self, run_id: str, devices: list[DeviceState]) -> None: ...
    def upsert_commands(self, commands: list[Command]) -> None: ...
    def record_acks(self, acks: list[Ack]) -> None: ...
    def record_interval_result(self, result: IntervalResult) -> None: ...
    def list_interval_results(self, run_id: str) -> list[IntervalResult]: ...
    def command_counts(self, run_id: str) -> tuple[int, int]:
        """(total commands, acked commands) for this run."""
        ...

    def ledger_summary(self, run_id: str) -> list[LedgerIntervalSummary]:
        """Per Market Interval: Commands issued, acked, expired, failed."""
        ...

    def latest_run_id(self) -> str | None: ...
