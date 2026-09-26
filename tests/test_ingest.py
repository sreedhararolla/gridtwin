from datetime import date

import pandas as pd
import pytest

from gridtwin.marketdata import cache, ingest_log
from gridtwin.marketdata.ingest import run_ingest
from gridtwin.marketdata.registry import DatasetSpec


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.settings, "marketdata_cache_dir", str(tmp_path))
    monkeypatch.setattr(cache.settings, "ercot_api_username", "")
    monkeypatch.setattr(cache.settings, "ercot_api_password", "")
    monkeypatch.setattr(cache.settings, "ercot_api_subscription_key", "")


def _ok_spec(calls: list) -> DatasetSpec:
    def fetch(key: str, day: date) -> pd.DataFrame:
        calls.append((key, day))
        return pd.DataFrame({"interval_start_utc": [day], "price_usd_per_mwh": [1.0]})

    return DatasetSpec("rt_spp", "NP6-905-CD", False, ("ALL",), fetch)


def test_ingest_fetches_each_missing_day_once():
    calls: list = []
    spec = _ok_spec(calls)

    summary = run_ingest([spec], date(2025, 12, 5), date(2025, 12, 7))

    assert summary.fetched == 3
    assert summary.errors == 0
    assert len(calls) == 3


def test_re_running_ingest_only_fetches_missing_days():
    calls: list = []
    spec = _ok_spec(calls)
    run_ingest([spec], date(2025, 12, 5), date(2025, 12, 7))
    calls.clear()

    summary = run_ingest([spec], date(2025, 12, 5), date(2025, 12, 8))

    assert summary.fetched == 1
    assert summary.skipped_cached == 3
    assert calls == [("ALL", date(2025, 12, 8))]


def test_a_failed_fetch_is_recorded_as_a_gap_and_does_not_stop_the_run():
    def flaky_fetch(key: str, day: date) -> pd.DataFrame:
        if day == date(2025, 12, 6):
            raise RuntimeError("ercot.com: 403")
        return pd.DataFrame({"interval_start_utc": [day], "price_usd_per_mwh": [1.0]})

    spec = DatasetSpec("rt_spp", "NP6-905-CD", False, ("ALL",), flaky_fetch)

    summary = run_ingest([spec], date(2025, 12, 5), date(2025, 12, 7))

    assert summary.fetched == 2
    assert summary.errors == 1
    assert cache.has_day("rt_spp", "ALL", date(2025, 12, 5))
    assert not cache.has_day("rt_spp", "ALL", date(2025, 12, 6))
    log = ingest_log.load_log()
    assert log[("rt_spp", "ALL", "2025-12-06")].status == "error"
    assert "403" in log[("rt_spp", "ALL", "2025-12-06")].message


def test_credential_gated_dataset_is_skipped_without_being_fetched():
    calls: list = []

    def fetch(key: str, day: date) -> pd.DataFrame:
        calls.append((key, day))
        raise AssertionError("must not be called without credentials")

    spec = DatasetSpec("load_forecast_vintages", "NP3-565-CD", True, ("ALL",), fetch)

    summary = run_ingest([spec], date(2025, 12, 5), date(2025, 12, 5))

    assert calls == []
    assert summary.skipped_pending_credentials == 1
    log = ingest_log.load_log()
    assert log[("load_forecast_vintages", "ALL", "2025-12-05")].status == "pending-credentials"


def test_default_window_start_excludes_pre_rtcb_days_unless_asked():
    calls: list = []
    spec = _ok_spec(calls)

    run_ingest([spec], date(2025, 12, 1), date(2025, 12, 5), include_pre_rtcb=False)

    assert calls == [("ALL", date(2025, 12, 5))]
