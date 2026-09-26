from datetime import UTC, datetime

import pytest

from gridtwin.replay.feed import validate_snapshot
from gridtwin.replay.models import FeedError

WHEN = datetime(2025, 12, 10, 12, 0, tzinfo=UTC)


def test_valid_price_returns_snapshot():
    snapshot = validate_snapshot(WHEN, "LZ_HOUSTON", 42.5)
    assert snapshot.rt_price_usd_per_mwh == 42.5


def test_missing_price_raises_feed_error():
    with pytest.raises(FeedError):
        validate_snapshot(WHEN, "LZ_HOUSTON", None)


def test_outlier_price_raises_feed_error():
    with pytest.raises(FeedError):
        validate_snapshot(WHEN, "LZ_HOUSTON", 9999.0)


def test_negative_price_raises_feed_error():
    with pytest.raises(FeedError):
        validate_snapshot(WHEN, "LZ_HOUSTON", -1.0)
