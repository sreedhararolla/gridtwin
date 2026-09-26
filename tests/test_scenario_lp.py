"""Seam A: the `lp` Strategy on the real spike day (2026-01-28, peak $1,284.81/MWh at
13:00 UTC). With a day-ahead forecast of the spike, the fleet holds charge into it instead
of spending it on the first $229 interval as naive does, and every plan is stored."""

from datetime import date

import pandas as pd
import pytest

from gridtwin.marketdata import cache, forecast
from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.settings import settings
from gridtwin.testing.scenario import run_scenario

pytestmark = pytest.mark.asyncio

SPIKE_DAY = date(2026, 1, 28)
SPIKE_DAY_FIXTURE = "data/fixtures/rtm_spp_lz_houston_2026-01-28.csv"
PEAK_INTERVAL = 28  # 13:00 UTC, $1,284.81/MWh


@pytest.fixture
def dam_cache(tmp_path, monkeypatch):
    """A cache holding one DAM day for the spike day: the hourly mean of the real RT day
    (a stand-in for the day-ahead price; CI has no ERCOT cache)."""
    monkeypatch.setattr(settings, "marketdata_cache_dir", str(tmp_path))
    forecast._dam_hours.cache_clear()
    rows = load_fixture_day(settings.settlement_point, SPIKE_DAY_FIXTURE)
    df = pd.DataFrame(rows, columns=["interval_start_utc", "price_usd_per_mwh"])
    df["interval_start_utc"] = pd.to_datetime(df["interval_start_utc"], utc=True).dt.floor("h")
    df = df.groupby("interval_start_utc", as_index=False)["price_usd_per_mwh"].mean()
    df["settlement_point"] = settings.settlement_point
    cache.write_day("dam_spp", "ALL", SPIKE_DAY, df, source="test")
    yield
    forecast._dam_hours.cache_clear()


async def run(strategy: str, run_id: str):
    return await run_scenario(
        run_id=run_id,
        fleet=settings.fleet_config().model_copy(
            update={"device_count": 200, "shard_count": 4, "seed": 7}
        ),
        settlement_point=settings.settlement_point,
        fixture_path=SPIKE_DAY_FIXTURE,
        discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        charge_threshold_usd=settings.naive_charge_threshold_usd,
        replay_speed=settings.replay_speed,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
        stale_after_seconds=30.0,
        strategy=strategy,
    )


async def test_lp_holds_charge_into_the_spike(dam_cache):
    lp = await run("lp", "scenario-lp-spike")
    naive = await run("naive", "scenario-naive-spike")

    assert lp.report.intervals == 96
    assert lp.report.reserve_violations == 0
    assert lp.report.within_tolerance_pct >= 95.0
    # The plan used each interval is stored for audit.
    assert all(r.strategy == "lp" for r in lp.results)
    assert all(r.forecast_source in {"dam_spp", "mixed"} for r in lp.results)
    assert [len(r.plan_mw) for r in lp.results] == [96] * 96
    assert all(r.strategy == "naive" and r.plan_mw == [] for r in naive.results)

    # Naive empties the fleet on the first $229 intervals; LP still delivers at the peak.
    assert naive.results[PEAK_INTERVAL].delivered_mw < 0.01
    assert lp.results[PEAK_INTERVAL].delivered_mw > 1.0
    assert lp.report.value_usd > naive.report.value_usd


async def test_lp_without_any_forecast_falls_back_to_naive(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "marketdata_cache_dir", str(tmp_path))
    forecast._dam_hours.cache_clear()
    outcome = await run("lp", "scenario-lp-no-forecast")
    assert outcome.report.reserve_violations == 0
    assert all(r.strategy == "naive" for r in outcome.results)
