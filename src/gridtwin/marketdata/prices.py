"""Any-day replay source: one Central-time trading day of RT prices for a settlement point,
read from the ingest cache (or, when no day is given, the checked-in fixture CSV that
tests and CI use)."""

from datetime import date, datetime
from functools import lru_cache

import pandas as pd

from gridtwin.marketdata import cache
from gridtwin.marketdata.fixtures import load_fixture_day


class DayNotCached(LookupError):
    pass


@lru_cache(maxsize=16)
def _cached_day_rows(settlement_point: str, day: date) -> tuple[tuple[datetime, float], ...]:
    if not cache.has_day("rt_spp", "ALL", day):
        raise DayNotCached(f"{day} is not in the rt_spp cache; run `make data` first")
    df = cache.read_day("rt_spp", "ALL", day)
    df = df[df["settlement_point"] == settlement_point]
    starts = pd.to_datetime(df["interval_start_utc"], utc=True)
    rows = sorted(
        (ts.to_pydatetime(), float(price))
        for ts, price in zip(starts, df["price_usd_per_mwh"], strict=True)
    )
    return tuple(rows)


def load_day_prices(
    settlement_point: str, day: date | None, fixture_path: str
) -> list[tuple[datetime, float]]:
    """(interval_start UTC, RT price $/MWh), sorted. `day=None` reads the fixture."""
    if day is None:
        return load_fixture_day(settlement_point, fixture_path)
    return list(_cached_day_rows(settlement_point, day))
