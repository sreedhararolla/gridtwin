"""In-memory LedgerRepo for the Scenario Runner (Seam A) and unit tests."""

from collections import defaultdict

from gridtwin.fleet.models import Ack, Command, DeviceState
from gridtwin.ledger.models import IntervalResult


class InMemoryLedgerRepo:
    def __init__(self) -> None:
        self._devices: dict[str, dict[str, DeviceState]] = defaultdict(dict)
        self._commands: dict[str, Command] = {}
        self._acked_keys: set[str] = set()
        self._results: dict[str, dict] = defaultdict(dict)
        self._latest_run_id: str | None = None

    def seed_devices(self, run_id: str, devices: list[DeviceState]) -> None:
        bucket = self._devices[run_id]
        for device in devices:
            bucket.setdefault(device.device_id, device)
        self._latest_run_id = run_id

    def get_devices(self, run_id: str) -> list[DeviceState]:
        return list(self._devices[run_id].values())

    def upsert_command(self, command: Command) -> None:
        self._commands.setdefault(command.idempotency_key, command)

    def record_ack(self, ack: Ack) -> None:
        if ack.applied:
            self._acked_keys.add(ack.idempotency_key)

    def update_device_soc(self, run_id: str, device_id: str, soc_pct: float) -> None:
        bucket = self._devices[run_id]
        bucket[device_id] = bucket[device_id].model_copy(update={"soc_pct": soc_pct})

    def record_interval_result(self, result: IntervalResult) -> None:
        self._results[result.run_id][result.interval_start] = result

    def list_interval_results(self, run_id: str) -> list[IntervalResult]:
        return sorted(self._results[run_id].values(), key=lambda r: r.interval_start)

    def command_counts(self, run_id: str) -> tuple[int, int]:
        commands = [c for c in self._commands.values() if c.run_id == run_id]
        acked = [c for c in commands if c.idempotency_key in self._acked_keys]
        return len(commands), len(acked)

    def latest_run_id(self) -> str | None:
        return self._latest_run_id
