from datetime import UTC, date, datetime

from gridtwin.marketdata.demo_days import rank_days
from gridtwin.marketdata.fixtures import load_fixture_day


def test_rank_days_orders_by_max_price_and_by_spread():
    rows = [
        (datetime(2025, 12, 1, 18, tzinfo=UTC), 10.0),
        (datetime(2025, 12, 1, 20, tzinfo=UTC), 15.0),
        (datetime(2025, 12, 2, 18, tzinfo=UTC), 5.0),
        (datetime(2025, 12, 2, 20, tzinfo=UTC), 200.0),
    ]

    by_max, by_spread = rank_days(rows)

    assert [s.day for s in by_max] == [datetime(2025, 12, 2).date(), datetime(2025, 12, 1).date()]
    assert by_max[0].max_price_usd_per_mwh == 200.0
    assert [s.day for s in by_spread] == [
        datetime(2025, 12, 2).date(),
        datetime(2025, 12, 1).date(),
    ]
    assert by_spread[0].spread_usd_per_mwh == 195.0


def test_rank_days_respects_top_n():
    rows = [(datetime(2025, 12, d, tzinfo=UTC), float(d)) for d in range(1, 6)]

    by_max, _ = rank_days(rows, top_n=2)

    assert len(by_max) == 2
    assert by_max[0].max_price_usd_per_mwh == 5.0


def test_rank_days_on_the_checked_in_fixture_finds_the_evening_scarcity_spike():
    """Buckets by the Central-time trading day, so the fixture's one real
    day (2025-12-10 CT) stays a single day even though its UTC timestamps
    span two UTC calendar dates."""
    fixture_rows = load_fixture_day()

    by_max, by_spread = rank_days(fixture_rows)

    assert len(by_max) == 1
    assert by_max[0].day == date(2025, 12, 10)
    assert by_max[0].max_price_usd_per_mwh > 100
    assert by_max[0].day == by_spread[0].day
