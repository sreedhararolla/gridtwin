"""The price forecast the `lp` Strategy plans on, known before the interval it prices.

Primary: the DAM SPP (hourly, published the day before) for the interval's hour, when the
day is in the `dam_spp` cache. Fallback: persistence, the RT price at the same interval one
day earlier (always known in time). See ADR-014 in docs/DECISIONS.md.
"""

from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd

from gridtwin.marketdata import cache
from gridtwin.marketdata.intervals import CENTRAL
from gridtwin.marketdata.prices import DayNotCached, load_day_prices

DAY = timedelta(days=1)


def trading_day(interval_start: datetime) -> date:
    return interval_start.astimezone(CENTRAL).date()


@lru_cache(maxsize=64)
def _dam_hours(settlement_point: str, day: date) -> dict[datetime, float] | None:
    """Hour start (UTC) -> DAM SPP for one trading day, or None if the day is not cached."""
    if not cache.has_day("dam_spp", "ALL", day):
        return None
    df = cache.read_day("dam_spp", "ALL", day)
    df = df[df["settlement_point"] == settlement_point]
    starts = pd.to_datetime(df["interval_start_utc"], utc=True)
    return {
        ts.to_pydatetime(): float(price)
        for ts, price in zip(starts, df["price_usd_per_mwh"], strict=True)
    }


def _rt_prices(settlement_point: str, day: date, fixture_path: str) -> dict[datetime, float]:
    try:
        return dict(load_day_prices(settlement_point, day, fixture_path))
    except DayNotCached:
        return {}


def forecast_prices(
    settlement_point: str, interval_starts: list[datetime], fixture_path: str
) -> tuple[list[float], str]:
    """One forecast price per interval, and its source: `dam_spp`, `persistence` or
    `mixed`. Gaps carry the previous forecast forward (the first falls back to 0)."""
    prices: list[float] = []
    sources: set[str] = set()
    last = 0.0
    for start in interval_starts:
        hour = start.replace(minute=0, second=0, microsecond=0)
        dam = _dam_hours(settlement_point, trading_day(start))
        price = dam.get(hour) if dam else None
        if price is not None:
            sources.add("dam_spp")
        else:
            previous = start - DAY
            price = _rt_prices(settlement_point, trading_day(previous), fixture_path).get(previous)
            if price is not None:
                sources.add("persistence")
        last = price if price is not None else last
        prices.append(last)
    source = sources.pop() if len(sources) == 1 else "mixed" if sources else "none"
    return prices, source
