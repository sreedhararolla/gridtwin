"""The Degradation Ladder (pure, Seam B): what an interval may dispatch on when the feed is
bad, and how the ladder recovers.

  L0 Optimized    a fresh, validated Market Snapshot and a fresh plan
  L1 Cached Plan  the last good plan, still inside its horizon
  L2 Safe Rule    discharge only if the last valid price is at or above the threshold
  L3 Hold         0 MW: no Commands at all

A feed failure drops the ladder to the best rung the data still supports (never better
than where it already is). It jumps back to L0 after N consecutive clean intervals; until
then it stays down, so one lucky reading does not undo a fault. `FeedGuard` is all the
state carried between intervals (by `ReplayRunWorkflow`, through continue-as-new)."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from gridtwin.ledger.models import IntervalResult
from gridtwin.replay.breaker import BreakerConfig, CircuitBreaker
from gridtwin.replay.feed import FeedHistory, ValidatorConfig

Level = Literal["L0", "L1", "L2", "L3"]
LEVELS: tuple[Level, ...] = ("L0", "L1", "L2", "L3")
LEVEL_NAMES = {"L0": "Optimized", "L1": "Cached Plan", "L2": "Safe Rule", "L3": "Hold"}
# ok | rejected (validator) | outage (the feed raised) | circuit-open (feed not called)
FeedStatus = Literal["ok", "rejected", "outage", "circuit-open"]
INTERVAL = timedelta(minutes=15)


class LadderConfig(BaseModel, frozen=True):
    cached_plan_intervals: int = Field(default=2, ge=0)  # a plan stays usable this long
    safe_rule_max_age_intervals: int = Field(default=8, ge=0)  # the last valid price, too
    recover_after_clean: int = Field(default=2, ge=1)  # N clean intervals back to L0
    breaker: BreakerConfig = BreakerConfig()
    validator: ValidatorConfig = ValidatorConfig()


class CachedPlan(BaseModel, frozen=True):
    target_mw: float
    planned_for: datetime
    valid_until: datetime  # exclusive: the end of the plan's horizon


class FeedGuard(BaseModel, frozen=True):
    level: Level = "L0"
    clean_streak: int = 0  # consecutive clean intervals while degraded
    breaker: CircuitBreaker = CircuitBreaker()
    history: FeedHistory = FeedHistory()
    cached_plan: CachedPlan | None = None


def cache_plan(
    guard: FeedGuard, interval_start: datetime, target_mw: float, config: LadderConfig
) -> FeedGuard:
    plan = CachedPlan(
        target_mw=target_mw,
        planned_for=interval_start,
        valid_until=interval_start + (1 + config.cached_plan_intervals) * INTERVAL,
    )
    return guard.model_copy(update={"cached_plan": plan})


def fallback_level(guard: FeedGuard, interval_start: datetime, config: LadderConfig) -> Level:
    """The best degraded rung the carried data still supports at `interval_start`."""
    plan = guard.cached_plan
    if plan is not None and plan.planned_for < interval_start < plan.valid_until:
        return "L1"
    last = guard.history.last_interval_start
    if last is not None and interval_start - last <= config.safe_rule_max_age_intervals * INTERVAL:
        return "L2"
    return "L3"


def _worse(a: Level, b: Level) -> Level:
    return max(a, b, key=LEVELS.index)


def step(
    guard: FeedGuard, interval_start: datetime, feed_ok: bool, config: LadderConfig
) -> FeedGuard:
    """The level for `interval_start`, given whether its snapshot came through clean.
    `guard.history` must already include this interval's snapshot when it did."""
    if not feed_ok:
        level = _worse(guard.level, fallback_level(guard, interval_start, config))
        return guard.model_copy(update={"level": level, "clean_streak": 0})
    if guard.level == "L0":
        return guard
    streak = guard.clean_streak + 1
    if streak >= config.recover_after_clean:
        return guard.model_copy(update={"level": "L0", "clean_streak": 0})
    level = _worse(guard.level, fallback_level(guard, interval_start, config))
    return guard.model_copy(update={"level": level, "clean_streak": streak})


def degraded_target_mw(
    level: Level,
    guard: FeedGuard,
    discharge_headroom_mw: float,
    discharge_threshold_usd: float,
) -> float | None:
    """The MW target below L0; None = L3 Hold, dispatch nothing."""
    if level == "L1" and guard.cached_plan is not None:
        return guard.cached_plan.target_mw
    if level == "L2" and guard.history.last_price is not None:
        # Safe Rule: never charge, discharge only on a proven-high last valid price. The
        # disaggregator and the Devices keep every Device above its Reserve Floor.
        return discharge_headroom_mw if guard.history.last_price >= discharge_threshold_usd else 0.0
    return None


class DegradationEvent(BaseModel, frozen=True):
    """One entry of the degradation timeline: a ladder transition or a rejected snapshot."""

    interval_start: datetime
    kind: Literal["level-change", "snapshot-rejected"]
    from_level: str
    to_level: str
    detail: str = ""


def degradation_timeline(results: list[IntervalResult]) -> list[DegradationEvent]:
    events: list[DegradationEvent] = []
    previous = "L0"
    for r in sorted(results, key=lambda r: r.interval_start):
        if r.feed_status == "rejected":
            events.append(
                DegradationEvent(
                    interval_start=r.interval_start,
                    kind="snapshot-rejected",
                    from_level=previous,
                    to_level=r.level,
                    detail=r.feed_detail,
                )
            )
        if r.level != previous:
            events.append(
                DegradationEvent(
                    interval_start=r.interval_start,
                    kind="level-change",
                    from_level=previous,
                    to_level=r.level,
                    detail=r.feed_detail or ("feed clean" if r.feed_status == "ok" else ""),
                )
            )
        previous = r.level
    return events
