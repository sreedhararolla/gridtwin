from datetime import UTC, date, timedelta
from itertools import pairwise

from gridtwin.marketdata.intervals import market_intervals_for_day


def test_normal_day_has_96_intervals():
    intervals = market_intervals_for_day(date(2025, 12, 10))
    assert len(intervals) == 96


def test_spring_forward_day_has_92_intervals():
    intervals = market_intervals_for_day(date(2026, 3, 8))
    assert len(intervals) == 92


def test_fall_back_day_has_100_intervals():
    intervals = market_intervals_for_day(date(2026, 11, 1))
    assert len(intervals) == 100


def test_intervals_are_utc_and_15_minutes_apart():
    intervals = market_intervals_for_day(date(2025, 12, 10))
    assert all(t.tzinfo == UTC for t in intervals)
    assert all(b - a == timedelta(minutes=15) for a, b in pairwise(intervals))
