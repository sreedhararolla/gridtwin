"""`demo-days`: rank cached days by max RT price and by intraday spread.

The ranking itself is a pure function over (day, price) rows so it can be
unit-tested against the checked-in fixture without touching the cache.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from gridtwin.marketdata import cache
from gridtwin.marketdata.intervals import CENTRAL


@dataclass(frozen=True)
class DayStat:
    day: date
    max_price_usd_per_mwh: float
    spread_usd_per_mwh: float


def rank_days(
    rows: list[tuple[datetime, float]], top_n: int = 10
) -> tuple[list[DayStat], list[DayStat]]:
    """Returns (top by max price, top by intraday spread), highest first.

    Buckets by the Central-time ERCOT trading day, not the raw UTC calendar
    date: a UTC calendar day splits an ERCOT day in two (CT is UTC-6/-5),
    which is not what a human picking "the Dec 10 spike day" means.
    """
    by_day: dict[date, list[float]] = defaultdict(list)
    for interval_start, price in rows:
        by_day[interval_start.astimezone(CENTRAL).date()].append(price)

    stats = [
        DayStat(
            day=day, max_price_usd_per_mwh=max(prices), spread_usd_per_mwh=max(prices) - min(prices)
        )
        for day, prices in by_day.items()
    ]
    by_max_price = sorted(stats, key=lambda s: s.max_price_usd_per_mwh, reverse=True)[:top_n]
    by_spread = sorted(stats, key=lambda s: s.spread_usd_per_mwh, reverse=True)[:top_n]
    return by_max_price, by_spread


def rank_cached_days(
    settlement_point: str = "LZ_HOUSTON", top_n: int = 10
) -> tuple[list[DayStat], list[DayStat]]:
    view = cache.dataset_view("rt_spp")
    df = view.filter(f"settlement_point = '{settlement_point}'").df()
    rows = list(zip(df["interval_start_utc"], df["price_usd_per_mwh"], strict=True))
    return rank_days(rows, top_n=top_n)
