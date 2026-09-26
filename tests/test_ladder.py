"""Seam B: the Degradation Ladder - stepping down on feed failures, the targets each rung
may dispatch, recovery after N clean intervals, and the degradation timeline."""

from datetime import UTC, datetime, timedelta

from gridtwin.dispatch.ladder import (
    FeedGuard,
    LadderConfig,
    cache_plan,
    degradation_timeline,
    degraded_target_mw,
    step,
)
from gridtwin.ledger.models import IntervalResult
from gridtwin.replay.feed import FeedHistory

T0 = datetime(2025, 12, 10, 18, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)
CONFIG = LadderConfig(cached_plan_intervals=2, safe_rule_max_age_intervals=4, recover_after_clean=2)


def at(i: int) -> datetime:
    return T0 + i * STEP


def healthy_guard(price: float = 40.0, target_mw: float = -1.5) -> FeedGuard:
    """L0 at interval 0 with a valid price and a cached plan."""
    guard = FeedGuard(history=FeedHistory(last_interval_start=at(0), recent_prices=[price]))
    return cache_plan(guard, at(0), target_mw, CONFIG)


def run(guard: FeedGuard, feed_ok: list[bool], start: int = 1) -> list[FeedGuard]:
    guards = []
    for i, ok in enumerate(feed_ok, start=start):
        if ok:  # a clean interval's snapshot joins the history first
            history = FeedHistory(
                last_interval_start=at(i),
                recent_prices=[*guard.history.recent_prices, 50.0],
            )
            guard = guard.model_copy(update={"history": history})
        guard = step(guard, at(i), ok, CONFIG)
        guards.append(guard)
    return guards


def test_clean_feed_stays_at_l0():
    assert [g.level for g in run(healthy_guard(), [True] * 4)] == ["L0"] * 4


def test_failures_step_down_l1_then_l2_as_the_cached_plan_runs_out_then_l3():
    levels = [g.level for g in run(healthy_guard(), [False] * 6)]
    # Plan cached at 0 covers 1-2; the last valid price (at 0) serves the Safe Rule to 4.
    assert levels == ["L1", "L1", "L2", "L2", "L3", "L3"]


def test_no_price_ever_means_l3_hold():
    assert step(FeedGuard(), at(0), False, CONFIG).level == "L3"


def test_recovers_to_l0_after_n_consecutive_clean_intervals():
    guards = run(healthy_guard(), [False, False, False, True, True, True])
    assert [g.level for g in guards] == ["L1", "L1", "L2", "L2", "L0", "L0"]


def test_a_failure_during_recovery_restarts_the_clean_count():
    guards = run(healthy_guard(), [False, False, False, True, False, True, True])
    assert [g.level for g in guards] == ["L1", "L1", "L2", "L2", "L2", "L2", "L0"]


def test_ladder_never_climbs_while_the_feed_is_failing():
    guards = run(healthy_guard(), [False] * 3)
    assert [g.level for g in guards] == ["L1", "L1", "L2"]
    later = step(guards[-1], at(4), False, CONFIG.model_copy(update={"cached_plan_intervals": 9}))
    assert later.level == "L2"  # a longer horizon does not bring the stale plan back


def test_l1_replays_the_cached_plan_target():
    assert degraded_target_mw("L1", healthy_guard(target_mw=-1.5), 2.0, 90.0) == -1.5


def test_l2_safe_rule_discharges_only_on_a_high_last_valid_price_and_never_charges():
    assert degraded_target_mw("L2", healthy_guard(price=120.0), 2.0, 90.0) == 2.0
    assert degraded_target_mw("L2", healthy_guard(price=10.0), 2.0, 90.0) == 0.0


def test_l3_holds_with_no_target_at_all():
    assert degraded_target_mw("L3", healthy_guard(), 2.0, 90.0) is None


def result(i: int, level: str, feed_status: str = "ok", detail: str = "") -> IntervalResult:
    return IntervalResult(
        run_id="r",
        interval_start=at(i),
        settlement_point="LZ_HOUSTON",
        price_usd_per_mwh=40.0,
        target_mw=0.0,
        achievable_mw=0.0,
        delivered_mw=0.0,
        level=level,
        dispatched_count=0,
        acked_count=0,
        reserve_violations=0,
        latency_ms=1.0,
        feed_status=feed_status,
        feed_detail=detail,
    )


def test_degradation_timeline_lists_every_transition_and_rejection():
    timeline = degradation_timeline(
        [
            result(0, "L0"),
            result(1, "L1", "rejected", "outlier"),
            result(2, "L2", "outage", "down"),
            result(3, "L2", "circuit-open"),
            result(4, "L0"),
        ]
    )
    assert [(e.kind, e.from_level, e.to_level) for e in timeline] == [
        ("snapshot-rejected", "L0", "L1"),
        ("level-change", "L0", "L1"),
        ("level-change", "L1", "L2"),
        ("level-change", "L2", "L0"),
    ]
    assert timeline[0].detail == "outlier"
