"""In-memory LedgerRepo for the Scenario Runner (Seam A) and unit tests. Like the Postgres
table, Commands are keyed by Idempotency Key: re-issuing a key never adds a row."""

from collections import defaultdict

from gridtwin.fleet.models import Ack, Command, DeviceState
from gridtwin.ledger.models import (
    CommandStatus,
    IntervalResult,
    LedgerIntervalSummary,
    command_status,
    summarize_ledger,
)


class InMemoryLedgerRepo:
    def __init__(self) -> None:
        self._devices: dict[str, dict[str, DeviceState]] = defaultdict(dict)
        self._commands: dict[str, Command] = {}
        self._acks: dict[str, Ack] = {}
        self._results: dict[str, dict] = defaultdict(dict)
        self._latest_run_id: str | None = None

    def seed_devices(self, run_id: str, devices: list[DeviceState]) -> None:
        bucket = self._devices[run_id]
        for device in devices:
            bucket.setdefault(device.device_id, device)
        self._latest_run_id = run_id

    def upsert_commands(self, commands: list[Command]) -> None:
        for command in commands:
            self._commands.setdefault(command.idempotency_key, command)

    def record_acks(self, acks: list[Ack]) -> None:
        for ack in acks:
            self._acks[ack.idempotency_key] = ack

    def record_interval_result(self, result: IntervalResult) -> None:
        self._results[result.run_id][result.interval_start] = result

    def list_interval_results(self, run_id: str) -> list[IntervalResult]:
        return sorted(self._results[run_id].values(), key=lambda r: r.interval_start)

    def command_counts(self, run_id: str) -> tuple[int, int]:
        commands = [c for c in self._commands.values() if c.run_id == run_id]
        acked = [
            c
            for c in commands
            if c.idempotency_key in self._acks and self._acks[c.idempotency_key].applied
        ]
        return len(commands), len(acked)

    def ledger_summary(self, run_id: str) -> list[LedgerIntervalSummary]:
        rows: list = []
        for command in self._commands.values():
            if command.run_id != run_id:
                continue
            ack = self._acks.get(command.idempotency_key)
            status: CommandStatus = "issued" if ack is None else command_status(ack.outcome)
            rows.append((command.interval_start, status, ack.delivered_mw if ack else 0.0))
        return summarize_ledger(rows)

    def latest_run_id(self) -> str | None:
        return self._latest_run_id
