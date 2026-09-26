"""Ticket 02's minimal fixture loader: reads the checked-in CSV fixture day.

Ticket 03 replaces this with the DuckDB + Parquet ingest cache; callers only rely on
`load_fixture_day` returning a window of (interval_start, price) for a settlement point,
so the interface shape survives that swap.
"""

import csv
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from gridtwin.settings import settings


@lru_cache(maxsize=8)
def _load_rows(fixture_path: str) -> tuple[tuple[datetime, str, float], ...]:
    rows = []
    with Path(fixture_path).open(newline="") as f:
        for row in csv.DictReader(f):
            interval_start = datetime.strptime(
                row["interval_start_utc"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
            rows.append((interval_start, row["settlement_point"], float(row["price_usd_per_mwh"])))
    rows.sort(key=lambda r: r[0])
    return tuple(rows)


def load_fixture_day(
    settlement_point: str | None = None, fixture_path: str | None = None
) -> list[tuple[datetime, float]]:
    point = settlement_point or settings.settlement_point
    path = fixture_path or settings.fixture_path
    return [(t, price) for t, sp, price in _load_rows(path) if sp == point]
