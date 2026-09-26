"""Seam B (pure domain): Recovery Time and the SLO table."""

from datetime import UTC, datetime, timedelta

from gridtwin.chaos.models import ChaosEvent
from gridtwin.chaos.slo import max_recovery_s, recovery_times, slo_rows
from gridtwin.ledger.models import IntervalResult

INTERVAL = datetime(2026, 1, 28, 13, tzinfo=UTC)
KILLED_AT = datetime(2026, 9, 26, 9, 32, 41, tzinfo=UTC)


def result(achievable_mw: float, delivered_mw: float, violations: int = 0) -> IntervalResult:
    return IntervalResult(
        run_id="r",
        interval_start=INTERVAL,
        settlement_point="LZ_HOUSTON",
        price_usd_per_mwh=1284.81,
        target_mw=achievable_mw,
        achievable_mw=achievable_mw,
        delivered_mw=delivered_mw,
        level="L0",
        dispatched_count=2000,
        acked_count=2000,
        reserve_violations=violations,
        latency_ms=4000.0,
    )


def kill(action: str = "apply", interval_start: datetime | None = INTERVAL) -> ChaosEvent:
    return ChaosEvent(
        run_id="r",
        at=KILLED_AT,
        scenario="worker-kill",
        action=action,
        target="worker-a",
        interval_start=interval_start,
    )


def test_recovery_is_fault_to_interrupted_interval_recorded():
    done = {INTERVAL: KILLED_AT + timedelta(seconds=3.9)}
    [recovery] = recovery_times([kill(), kill("clear", None)], done)
    assert recovery.recovery_s == 3.9
    assert recovery.target == "worker-a"


def test_interval_not_yet_recorded_has_no_recovery():
    [recovery] = recovery_times([kill()], {})
    assert recovery.recovery_s is None
    assert max_recovery_s([recovery]) is None


def test_slo_table_passes_a_clean_recovery():
    recoveries = recovery_times([kill()], {INTERVAL: KILLED_AT + timedelta(seconds=4)})
    rows = slo_rows([result(20.0, 19.8)], recoveries, 0.05, 15.0, expected_intervals=1)
    assert [(r.name, r.actual, r.ok) for r in rows] == [
        ("Within tolerance", "100.0 %", True),
        ("Reserve violations", "0", True),
        ("Missed intervals", "0", True),
        ("Recovery time", "4.0 s", True),
    ]


def test_slo_table_flags_misses():
    recoveries = recovery_times([kill()], {INTERVAL: KILLED_AT + timedelta(seconds=40)})
    rows = slo_rows([result(20.0, 10.0, violations=2)], recoveries, 0.05, 15.0, 3)
    assert [r.ok for r in rows] == [False, False, False, False]
    assert rows[2].actual == "2"


def test_watt_level_rounding_is_within_tolerance():
    # A drained fleet: 2.16 W achievable, Acks rounded to 2 W.
    rows = slo_rows([result(2.156e-6, 2e-6)], [], 0.05, 15.0)
    assert rows[0].ok
    rows = slo_rows([result(0.0, 0.002)], [], 0.05, 15.0)
    assert not rows[0].ok


def test_no_faults_meets_the_recovery_slo():
    rows = slo_rows([result(20.0, 20.0)], [], 0.05, 15.0)
    assert (rows[-1].actual, rows[-1].ok) == ("no faults", True)
