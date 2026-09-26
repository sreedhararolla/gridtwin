"""Seed one real-shaped RT SPP day into the cache from the checked-in fixture.

Only needed while ERCOT is unreachable from a given machine (see
docs/DECISIONS.md): it makes the Data tab and `demo-days` demoable today,
using the same cache the real ingest writes to. Rows are tagged
`source=fixture_seed` so nothing pretends this is a live ERCOT pull.
"""

from datetime import date

import pandas as pd

from gridtwin.marketdata import cache
from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.settings import settings

FIXTURE_DAY = date(2025, 12, 10)


def seed_fixture_day(day: date = FIXTURE_DAY) -> None:
    rows = load_fixture_day()
    df = pd.DataFrame(
        {
            "interval_start_utc": [t for t, _ in rows],
            "settlement_point": settings.settlement_point,
            "price_usd_per_mwh": [p for _, p in rows],
        }
    )
    cache.write_day("rt_spp", "ALL", day, df, source="fixture_seed")
