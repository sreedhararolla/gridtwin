"""Interval Result: the per-interval record the dashboard and Scenario Report read (CONTEXT.md)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from gridtwin.fleet.models import AckOutcome

# A Command's lifecycle in the Command Ledger: issued -> acked / expired / failed.
CommandStatus = Literal["issued", "acked", "expired", "failed"]
_STATUS_OF_OUTCOME: dict[AckOutcome, CommandStatus] = {
    "applied": "acked",
    "expired": "expired",
    "superseded": "expired",
    "failed": "failed",
}


def command_status(outcome: AckOutcome) -> CommandStatus:
    return _STATUS_OF_OUTCOME[outcome]


class LedgerIntervalSummary(BaseModel, frozen=True):
    """The Command Ledger for one Market Interval: every Command issued, by status."""

    interval_start: datetime
    issued: int  # all Commands issued (one ledger row per Idempotency Key)
    acked: int
    expired: int  # ignored by the Device: expired or superseded
    failed: int  # the Device could not act
    unacked: int  # still issued: no Ack recorded
    delivered_mw: float


def summarize_ledger(
    rows: list[tuple[datetime, CommandStatus, float]],
) -> list[LedgerIntervalSummary]:
    """(interval_start, status, delivered_mw) per ledger row -> one summary per interval."""
    buckets: dict[datetime, dict[str, float]] = {}
    for interval_start, status, delivered_mw in rows:
        b = buckets.setdefault(
            interval_start,
            {"issued": 0, "acked": 0, "expired": 0, "failed": 0, "delivered_mw": 0.0},
        )
        b["issued"] += 1
        b[status] += 0 if status == "issued" else 1
        b["delivered_mw"] += delivered_mw
    return [
        LedgerIntervalSummary(
            interval_start=interval_start,
            issued=int(b["issued"]),
            acked=int(b["acked"]),
            expired=int(b["expired"]),
            failed=int(b["failed"]),
            unacked=int(b["issued"] - b["acked"] - b["expired"] - b["failed"]),
            delivered_mw=round(b["delivered_mw"], 6),
        )
        for interval_start, b in sorted(buckets.items())
    ]


class IntervalResult(BaseModel, frozen=True):
    run_id: str
    interval_start: datetime
    settlement_point: str
    price_usd_per_mwh: float
    target_mw: float
    achievable_mw: float
    delivered_mw: float
    level: str
    dispatched_count: int
    acked_count: int
    reserve_violations: int
    latency_ms: float  # plan -> all shard acks, the interval's dispatch latency
    budget_ms: float = 0.0  # the interval's wall budget: 900 s / replay speed
    online_devices: int = 0  # non-stale Devices in Fleet State at decision time
    shard_count: int = 0
    soc_p10_pct: float = 0.0
    soc_p50_pct: float = 0.0
    soc_p90_pct: float = 0.0
    duplicate_deliveries: int = 0  # the same Command arriving at a Shard more than once
    duplicate_effects: int = 0  # a Device acting on the same key twice (must be 0)
    retried_dispatches: int = 0  # Shard dispatch activities that succeeded on a retry
