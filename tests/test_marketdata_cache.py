from datetime import date

import duckdb
import pandas as pd

from gridtwin.marketdata import cache


def test_write_day_then_has_day_and_cached_days(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.settings, "marketdata_cache_dir", str(tmp_path))
    day = date(2025, 12, 10)
    df = pd.DataFrame(
        {
            "interval_start_utc": [f"2025-12-10T00:{m:02d}:00Z" for m in (0, 15)],
            "price": [10.0, 20.0],
        }
    )

    assert not cache.has_day("rt_spp", "LZ_HOUSTON", day)
    written = cache.write_day("rt_spp", "LZ_HOUSTON", day, df)

    assert written.exists()
    assert cache.has_day("rt_spp", "LZ_HOUSTON", day)
    assert cache.cached_days("rt_spp", "LZ_HOUSTON") == {day}


def test_write_day_tags_the_regime(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.settings, "marketdata_cache_dir", str(tmp_path))
    df = pd.DataFrame({"price": [1.0]})

    pre_path = cache.write_day("rt_spp", "LZ_HOUSTON", date(2025, 1, 1), df)
    post_path = cache.write_day("rt_spp", "LZ_HOUSTON", date(2025, 12, 10), df)

    assert duckdb.connect().sql(f"SELECT regime FROM read_parquet('{pre_path}')").fetchone()[0] == (
        "pre_rtcb"
    )
    assert duckdb.connect().sql(f"SELECT regime FROM read_parquet('{post_path}')").fetchone()[
        0
    ] == ("post_rtcb")


def test_write_day_is_atomic_no_partial_file_left_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.settings, "marketdata_cache_dir", str(tmp_path))
    df = pd.DataFrame({"price": [1.0]})
    day = date(2025, 12, 10)

    cache.write_day("rt_spp", "LZ_HOUSTON", day, df)

    directory = cache.dataset_dir("rt_spp", "LZ_HOUSTON")
    files = list(directory.iterdir())
    assert files == [cache.day_path("rt_spp", "LZ_HOUSTON", day)]
