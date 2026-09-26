from datetime import date

import pandas as pd
import pytest

from gridtwin.marketdata import cache
from gridtwin.marketdata.audit import build_audit
from gridtwin.marketdata.ingest import run_ingest
from gridtwin.marketdata.registry import DatasetSpec


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.settings, "marketdata_cache_dir", str(tmp_path))
    monkeypatch.setattr(cache.settings, "ercot_api_username", "")
    monkeypatch.setattr(cache.settings, "ercot_api_password", "")
    monkeypatch.setattr(cache.settings, "ercot_api_subscription_key", "")


def test_audit_reports_present_missing_and_pending_credentials_explicitly():
    def flaky_fetch(key: str, day: date) -> pd.DataFrame:
        if day == date(2025, 12, 6):
            raise RuntimeError("ercot.com: 403 Forbidden")
        return pd.DataFrame({"interval_start_utc": [day], "price_usd_per_mwh": [1.0]})

    rt_spp = DatasetSpec("rt_spp", "NP6-905-CD", False, ("ALL",), flaky_fetch)
    vintages = DatasetSpec(
        "load_forecast_vintages", "NP3-565-CD (all vintages)", True, ("ALL",), flaky_fetch
    )
    run_ingest([rt_spp, vintages], date(2025, 12, 5), date(2025, 12, 7))

    rows = build_audit([rt_spp, vintages], date(2025, 12, 5), date(2025, 12, 7))

    rt_spp_row = next(r for r in rows if r.dataset == "rt_spp")
    assert rt_spp_row.present == 2
    assert rt_spp_row.missing == 1
    assert "403" in rt_spp_row.sample_gap_reason

    vintages_row = next(r for r in rows if r.dataset == "load_forecast_vintages")
    assert vintages_row.present == 0
    assert vintages_row.pending_credentials == 3
    assert vintages_row.missing == 0


def test_audit_never_silently_drops_a_never_attempted_day():
    spec = DatasetSpec("rt_spp", "NP6-905-CD", False, ("ALL",), lambda key, day: pd.DataFrame())

    rows = build_audit([spec], date(2025, 12, 5), date(2025, 12, 7))

    row = rows[0]
    assert row.total_days == 3
    assert row.present == 0
    assert row.missing == 3
    assert row.sample_gap_reason == "not yet attempted"
