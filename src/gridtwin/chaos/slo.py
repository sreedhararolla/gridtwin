"""Pure SLO arithmetic for a Replay Run under chaos (Seam B): Recovery Time per fault and
the SLO table (target vs actual). No IO."""

from datetime import datetime

from gridtwin.chaos.models import ChaosEvent, RecoveryTime, SloRow
from gridtwin.ledger.models import IntervalResult

WITHIN_TOLERANCE_TARGET_PCT = 95.0
# Acks round to 1 W per Device; a watt-level target must not fail on rounding (ADR-010).
TOLERANCE_FLOOR_MW = 0.001


def within_tolerance(result: IntervalResult, tolerance_pct: float) -> bool:
    """Delivered MW within ±tolerance of the Achievable Target (or 1 kW, if larger)."""
    gap = abs(result.achievable_mw - result.delivered_mw)
    return gap <= max(tolerance_pct * abs(result.achievable_mw), TOLERANCE_FLOOR_MW)


def within_tolerance_pct(results: list[IntervalResult], tolerance_pct: float) -> float:
    if not results:
        return 0.0
    hits = sum(1 for r in results if within_tolerance(r, tolerance_pct))
    return 100.0 * hits / len(results)


def recovery_times(
    events: list[ChaosEvent], completed_at: dict[datetime, datetime]
) -> list[RecoveryTime]:
    """Recovery Time = fault applied -> the interrupted interval's Interval Result recorded.

    `completed_at` maps interval_start -> when its Interval Result was written."""
    recoveries = []
    for event in events:
        if event.action != "apply" or event.interval_start is None:
            continue
        done = completed_at.get(event.interval_start)
        recoveries.append(
            RecoveryTime(
                at=event.at,
                scenario=event.scenario,
                target=event.target,
                interval_start=event.interval_start,
                recovery_s=None if done is None else max((done - event.at).total_seconds(), 0.0),
            )
        )
    return recoveries


def max_recovery_s(recoveries: list[RecoveryTime]) -> float | None:
    """The worst Recovery Time; None if any fault's interval never completed."""
    if any(r.recovery_s is None for r in recoveries):
        return None
    return max((r.recovery_s or 0.0 for r in recoveries), default=0.0)


def slo_rows(
    results: list[IntervalResult],
    recoveries: list[RecoveryTime],
    tolerance_pct: float,
    recovery_target_s: float,
    expected_intervals: int | None = None,
) -> list[SloRow]:
    tolerance_actual = within_tolerance_pct(results, tolerance_pct)
    violations = sum(r.reserve_violations for r in results)
    rows = [
        SloRow(
            name="Within tolerance",
            # ASCII only: the SLO table is also printed to Windows cp1252 consoles.
            target=f">= {WITHIN_TOLERANCE_TARGET_PCT:.0f} % (+/-{tolerance_pct * 100:.0f} %)",
            actual=f"{tolerance_actual:.1f} %",
            ok=bool(results) and tolerance_actual >= WITHIN_TOLERANCE_TARGET_PCT,
        ),
        SloRow(
            name="Reserve violations",
            target="0",
            actual=str(violations),
            ok=violations == 0,
        ),
    ]
    duplicate_effects = sum(r.duplicate_effects for r in results)
    duplicate_deliveries = sum(r.duplicate_deliveries for r in results)
    rows.append(
        SloRow(
            name="Duplicate effects",
            target="0",
            actual=f"{duplicate_effects} ({duplicate_deliveries} dup deliveries)",
            ok=duplicate_effects == 0,
        )
    )
    if expected_intervals is not None:
        missed = max(expected_intervals - len(results), 0)
        rows.append(SloRow(name="Missed intervals", target="0", actual=str(missed), ok=missed == 0))
    worst = max_recovery_s(recoveries)
    rows.append(
        SloRow(
            name="Recovery time",
            target=f"<= {recovery_target_s:.0f} s",
            actual="no faults"
            if not recoveries
            else ("not recovered" if worst is None else f"{worst:.1f} s"),
            ok=worst is not None and worst <= recovery_target_s,
        )
    )
    return rows
