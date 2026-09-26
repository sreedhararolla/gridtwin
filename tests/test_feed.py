"""Seam B: the feed validator - range, staleness, monotonic timestamps, outliers."""

from datetime import UTC, datetime, timedelta

import pytest

from gridtwin.replay.feed import (
    FeedHistory,
    FeedReading,
    ValidatorConfig,
    remember,
    validate_snapshot,
)
from gridtwin.replay.models import FeedError

WHEN = datetime(2025, 12, 10, 12, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)
CALM = FeedHistory(last_interval_start=WHEN - STEP, recent_prices=[30.0 + i for i in range(16)])


def reading(price: float | None, observed: datetime | None = WHEN) -> FeedReading:
    return FeedReading(
        interval_start=WHEN,
        observed_interval_start=observed,
        settlement_point="LZ_HOUSTON",
        raw_price=price,
    )


def test_valid_price_returns_snapshot():
    snapshot = validate_snapshot(reading(42.5))
    assert snapshot.rt_price_usd_per_mwh == 42.5
    assert snapshot.interval_start == WHEN


def test_missing_price_raises_feed_error():
    with pytest.raises(FeedError, match="no price"):
        validate_snapshot(reading(None, observed=None))


@pytest.mark.parametrize("price", [9999.0, 5000.01, -500.01])
def test_out_of_range_price_raises_feed_error(price: float):
    with pytest.raises(FeedError, match="sane bounds"):
        validate_snapshot(reading(price))


def test_negative_prices_are_real_in_ercot_and_pass():
    assert validate_snapshot(reading(-12.0)).rt_price_usd_per_mwh == -12.0


def test_stale_row_raises_feed_error():
    with pytest.raises(FeedError, match="stale"):
        validate_snapshot(reading(40.0, observed=WHEN - STEP))


def test_non_monotonic_interval_raises_feed_error():
    history = FeedHistory(last_interval_start=WHEN, recent_prices=[40.0])
    with pytest.raises(FeedError, match="non-monotonic"):
        validate_snapshot(reading(40.0), history)


def test_outlier_against_recent_distribution_raises_feed_error():
    tight = ValidatorConfig(outlier_z=10.0, outlier_mad_floor_usd=5.0)
    with pytest.raises(FeedError, match="outlier"):
        validate_snapshot(reading(400.0), CALM, tight)


def test_real_scarcity_spike_passes_default_outlier_check():
    # The Jan 28, 2026 LZ_HOUSTON peak ($1,284.81) after a calm morning must be tradable.
    assert validate_snapshot(reading(1284.81), CALM).rt_price_usd_per_mwh == 1284.81
    assert validate_snapshot(reading(5000.0), CALM).rt_price_usd_per_mwh == 5000.0


def test_outlier_check_waits_for_enough_samples():
    tight = ValidatorConfig(outlier_z=10.0, outlier_mad_floor_usd=5.0)
    few = FeedHistory(last_interval_start=WHEN - STEP, recent_prices=[30.0, 31.0])
    assert validate_snapshot(reading(400.0), few, tight).rt_price_usd_per_mwh == 400.0


def test_remember_keeps_a_bounded_window_of_valid_prices():
    config = ValidatorConfig(window=3)
    history = FeedHistory()
    for i in range(5):
        at = WHEN + i * STEP
        snapshot = validate_snapshot(
            FeedReading(
                interval_start=at,
                observed_interval_start=at,
                settlement_point="LZ_HOUSTON",
                raw_price=float(i),
            ),
            history,
            config,
        )
        history = remember(history, snapshot, config)
    assert history.recent_prices == [2.0, 3.0, 4.0]
    assert history.last_price == 4.0
    assert history.last_interval_start == WHEN + 4 * STEP
