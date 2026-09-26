"""`data-audit`: report every gap explicitly. Nothing is silently skipped."""

from dataclasses import dataclass
from datetime import date

from gridtwin.marketdata import cache, ingest_log
from gridtwin.marketdata.registry import DatasetSpec
from gridtwin.marketdata.window import days_in_window


@dataclass
class AuditRow:
    dataset: str
    key: str
    report_id: str
    total_days: int
    present: int
    missing: int
    pending_credentials: int
    sample_gap_reason: str | None


def build_audit(
    registry: list[DatasetSpec], start: date, end: date, include_pre_rtcb: bool = False
) -> list[AuditRow]:
    if not include_pre_rtcb:
        start = max(start, cache.RTCB_GO_LIVE)
    days = days_in_window(start, end)
    entries = ingest_log.load_log()

    rows = []
    for spec in registry:
        for key in spec.keys:
            gaps = [d for d in days if not cache.has_day(spec.name, key, d)]
            pending = [
                d for d in gaps if _status(entries, spec.name, key, d) == "pending-credentials"
            ]
            errors = [d for d in gaps if _status(entries, spec.name, key, d) == "error"]
            never_attempted = [d for d in gaps if _status(entries, spec.name, key, d) is None]

            sample_reason = None
            if errors:
                sample_reason = entries[(spec.name, key, errors[0].isoformat())].message
            elif never_attempted:
                sample_reason = "not yet attempted"

            rows.append(
                AuditRow(
                    dataset=spec.name,
                    key=key,
                    report_id=spec.report_id,
                    total_days=len(days),
                    present=len(days) - len(gaps),
                    missing=len(errors) + len(never_attempted),
                    pending_credentials=len(pending),
                    sample_gap_reason=sample_reason,
                )
            )
    return rows


def _status(entries: dict, dataset: str, key: str, day: date) -> str | None:
    entry = entries.get((dataset, key, day.isoformat()))
    return entry.status if entry else None


def format_audit(rows: list[AuditRow]) -> str:
    lines = [
        f"{'dataset':<24} {'key':<14} {'report':<26} {'present':>7} {'missing':>7} "
        f"{'pending-keys':>12}  reason"
    ]
    for row in rows:
        lines.append(
            f"{row.dataset:<24} {row.key:<14} {row.report_id:<26} {row.present:>7} "
            f"{row.missing:>7} {row.pending_credentials:>12}  {row.sample_gap_reason or ''}"
        )
    return "\n".join(lines)
