"""A small JSON sidecar recording the *reason* a day is missing.

The cache itself only records success (a Parquet file exists). `data-audit`
needs to tell "never attempted" apart from "attempted and failed" and from
"skipped, pending credentials" — this log is where that distinction lives.
Never committed (lives under the gitignored cache root).
"""

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from gridtwin.marketdata.cache import cache_root


@dataclass
class LogEntry:
    dataset: str
    key: str
    day: str
    status: str  # "error" | "pending-credentials"
    message: str


def log_path() -> Path:
    return cache_root() / "_ingest_log.json"


def load_log() -> dict[tuple[str, str, str], LogEntry]:
    path = log_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {(e["dataset"], e["key"], e["day"]): LogEntry(**e) for e in raw}


def save_log(entries: dict[tuple[str, str, str], LogEntry]) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(e) for e in entries.values()], indent=2))


def record(
    entries: dict[tuple[str, str, str], LogEntry],
    dataset: str,
    key: str,
    day: date,
    status: str,
    message: str,
) -> None:
    entries[(dataset, key, day.isoformat())] = LogEntry(
        dataset, key, day.isoformat(), status, message
    )


def clear(entries: dict[tuple[str, str, str], LogEntry], dataset: str, key: str, day: date) -> None:
    entries.pop((dataset, key, day.isoformat()), None)
