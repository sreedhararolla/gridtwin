"""Seam B: the scarcity-risk feature builder and its look-ahead guard, the label
threshold and the probability metrics (pure, no IO)."""

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from gridtwin.risk.features import (
    FEATURE_NAMES,
    HORIZON_INTERVALS,
    INTERVAL,
    KnownInputs,
    LookaheadError,
    Obs,
    build_features,
    dam_known_at,
    rt_known_at,
    spike_threshold,
    targets_from,
    temperature_known_at,
)
from gridtwin.risk.metrics import brier, calibration, pr_auc

# 2026-01-28 12:00 Central = 18:00 UTC
DECISION = datetime(2026, 1, 28, 18, 0, tzinfo=UTC)


def rt_history(end: datetime, n: int = 96, price: float = 30.0) -> list[Obs]:
    starts = [end - INTERVAL * k for k in range(n, 0, -1)]  # the last one ends at `end`
    return [Obs(s, rt_known_at(s), price + i) for i, s in enumerate(starts)]


def dam_day(day: date, price: float = 40.0) -> list[Obs]:
    midnight_ct = datetime(day.year, day.month, day.day, 6, tzinfo=UTC)  # CST = UTC-6
    return [Obs(midnight_ct + timedelta(hours=h), dam_known_at(day), price + h) for h in range(24)]


def temps(end: datetime) -> list[Obs]:
    hours = [end - timedelta(hours=k) for k in range(4, 0, -1)]
    return [Obs(h, temperature_known_at(h), 10.0 + i) for i, h in enumerate(hours)]


def known() -> KnownInputs:
    return KnownInputs(
        rt=rt_history(DECISION), dam=dam_day(date(2026, 1, 28)), temperature=temps(DECISION)
    )


def test_builds_one_row_per_upcoming_interval():
    rows = build_features(DECISION, known())
    assert len(rows) == HORIZON_INTERVALS
    assert all(len(row) == len(FEATURE_NAMES) for row in rows)
    assert targets_from(DECISION)[0] == DECISION
    features = dict(zip(FEATURE_NAMES, rows[4], strict=True))
    assert features["lead_intervals"] == 4
    assert features["hour_ct"] == 13.0  # one hour after 12:00 Central
    assert features["rt_last"] == 30.0 + 95
    assert features["rt_max_4h"] == 30.0 + 95
    assert features["dam_target"] == 40.0 + 13
    assert features["dam_day_max"] == 40.0 + 23
    assert features["temperature_c"] == 13.0
    assert features["temperature_change_3h"] == 3.0


def test_rejects_an_rt_price_for_an_interval_that_has_not_ended():
    future = Obs(DECISION, rt_known_at(DECISION), 5000.0)  # the interval being decided
    inputs = KnownInputs(rt=[*rt_history(DECISION), future], dam=[], temperature=[])
    with pytest.raises(LookaheadError, match="rt"):
        build_features(DECISION, inputs)


def test_rejects_tomorrows_dam_before_it_is_published():
    morning = datetime(2026, 1, 28, 15, 0, tzinfo=UTC)  # 09:00 Central, before 13:30
    inputs = KnownInputs(rt=[], dam=dam_day(date(2026, 1, 29)), temperature=[])
    with pytest.raises(LookaheadError, match="dam"):
        build_features(morning, inputs)
    published = datetime(2026, 1, 28, 19, 30, tzinfo=UTC)  # 13:30 Central
    assert len(build_features(published, inputs)) == HORIZON_INTERVALS


def test_rejects_a_temperature_hour_that_has_not_ended():
    inputs = KnownInputs(
        rt=[], dam=[], temperature=[Obs(DECISION, temperature_known_at(DECISION), 30.0)]
    )
    with pytest.raises(LookaheadError, match="temperature"):
        build_features(DECISION, inputs)


def test_missing_inputs_are_nan_not_zero():
    rows = build_features(DECISION, KnownInputs(rt=[], dam=[], temperature=[]))
    features = dict(zip(FEATURE_NAMES, rows[0], strict=True))
    for name in ("rt_last", "dam_target", "temperature_c", "forecast_error_today"):
        assert math.isnan(features[name]), name


def test_spike_threshold_is_the_quantile_of_training_prices():
    prices = [float(p) for p in range(101)]  # 0..100
    assert spike_threshold(prices, 0.99) == pytest.approx(99.0)
    assert spike_threshold(prices, 0.5) == pytest.approx(50.0)
    with pytest.raises(ValueError):
        spike_threshold([], 0.99)


def test_metrics():
    y = np.array([0, 0, 1, 1])
    assert brier(y, np.array([0.0, 0.0, 1.0, 1.0])) == 0.0
    assert brier(y, np.array([0.5] * 4)) == pytest.approx(0.25)
    assert pr_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    assert pr_auc(np.array([0, 0]), np.array([0.1, 0.2])) is None
    bins = calibration(y, np.array([0.005, 0.005, 0.5, 0.5]))
    assert sum(b.count for b in bins) == 4
    top = next(b for b in bins if b.lo == 0.4)
    assert top.count == 2 and top.observed_rate == 1.0
