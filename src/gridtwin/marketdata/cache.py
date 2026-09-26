"""The queryable ingest cache: one Parquet file per dataset per key per day.

Never committed (see .gitignore: data/cache/). DuckDB unifies everything in
UTC with a `regime` column so callers never need to know the cache is a pile
of Parquet files on disk.
"""

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from gridtwin.settings import settings

RTCB_GO_LIVE = date(2025, 12, 5)


def regime_for(day: date) -> str:
    return "post_rtcb" if day >= RTCB_GO_LIVE else "pre_rtcb"


def cache_root() -> Path:
    return Path(settings.marketdata_cache_dir)


def dataset_dir(dataset: str, key: str) -> Path:
    return cache_root() / dataset / key


def day_path(dataset: str, key: str, day: date) -> Path:
    return dataset_dir(dataset, key) / f"{day.isoformat()}.parquet"


def has_day(dataset: str, key: str, day: date) -> bool:
    return day_path(dataset, key, day).exists()


def write_day(
    dataset: str, key: str, day: date, df: pd.DataFrame, source: str = "ercot_live"
) -> Path:
    """Write one day's rows atomically: write to a temp file, then rename.

    A crash mid-write never leaves a half-written file that `has_day` would
    mistake for a completed fetch. Written with DuckDB's own Parquet writer
    so the ingest cache needs no separate pyarrow/fastparquet dependency.
    `source` records provenance (e.g. `fixture_seed` for the placeholder day
    ADR-008 seeds while ERCOT is unreachable) so the cache never claims a
    non-live day is a real ERCOT pull.
    """
    out_dir = dataset_dir(dataset, key)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df["regime"] = regime_for(day)
    df["source"] = source

    final_path = day_path(dataset, key, day)
    tmp_path = final_path.with_suffix(".parquet.tmp")
    duckdb.connect().sql("SELECT * FROM df").write_parquet(str(tmp_path))
    tmp_path.replace(final_path)
    return final_path


def read_day(dataset: str, key: str, day: date) -> pd.DataFrame:
    return duckdb.connect().sql(f"SELECT * FROM read_parquet('{day_path(dataset, key, day)}')").df()


def dataset_view(dataset: str) -> duckdb.DuckDBPyRelation:
    """A DuckDB relation over every cached day of `dataset`, across all keys."""
    glob = str(cache_root() / dataset / "**" / "*.parquet")
    con = duckdb.connect()
    return con.sql(f"SELECT * FROM read_parquet('{glob}', union_by_name=true)")


def cached_days(dataset: str, key: str) -> set[date]:
    directory = dataset_dir(dataset, key)
    if not directory.exists():
        return set()
    return {
        date.fromisoformat(p.stem)
        for p in directory.glob("*.parquet")
        if not p.stem.endswith(".tmp")
    }
