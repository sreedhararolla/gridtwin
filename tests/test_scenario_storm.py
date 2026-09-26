"""Seam A: Storm mode on the real spike day (2026-01-28, peak $1,284.81/MWh at 13:00 UTC).
The Risk Curve (injected: CI has no stored curves) sees a tight spell around the peak. The
Reserve Floor rises to 60% two hours ahead, the LP charges the fleet up to it, and no Device
is ever discharged below the dynamic floor."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from gridtwin.marketdata import cache, forecast
from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.settings import settings
from gridtwin.storm.reserve import StormConfig, StormSignals
from gridtwin.testing.scenario import run_scenario

pytestmark = pytest.mark.asyncio

SPIKE_DAY = date(2026, 1, 28)
SPIKE_DAY_FIXTURE = "data/fixtures/rtm_spp_lz_houston_2026-01-28.csv"
TIGHT = range(26, 32)  # 12:30-14:00 UTC, around the 13:00 peak
STORM = StormConfig(enabled=True, storm_floor_pct=0.6, risk_threshold=0.25, lead_intervals=8)


@pytest.fixture
def dam_cache(tmp_path, monkeypatch):
    """One DAM day for the spike day: the hourly mean of the real RT day (a stand-in for the
    day-ahead price; CI has no ERCOT cache)."""
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


def tight_spell_signals():
    first: datetime = load_fixture_day(settings.settlement_point, SPIKE_DAY_FIXTURE)[0][0]

    def signals(_settlement_point: str, interval_start: datetime) -> StormSignals:
        k = (interval_start - first) // timedelta(minutes=15)
        return StormSignals(p_spike=[0.6 if k + t in TIGHT else 0.02 for t in range(16)])

    return signals


async def test_dynamic_floor_rises_before_the_tight_spell_and_is_never_violated(dam_cache):
    outcome = await run_scenario(
        run_id="scenario-storm-spike",
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
        strategy="lp",
        storm=STORM,
        storm_signals=tight_spell_signals(),
    )
    report, results = outcome.report, outcome.results

    assert report.intervals == 96
    assert report.reserve_violations == 0  # judged by every Device against the dynamic floor
    assert report.max_reserve_floor_pct == pytest.approx(60.0)
    # Raised from 26 - 8 = 18 through the end of the spell (31): 14 intervals.
    raised = [i for i, r in enumerate(results) if r.reserve_reasons]
    assert raised == list(range(18, 32))
    assert report.raised_floor_intervals == 14
    assert results[17].reserve_floor_pct == pytest.approx(20.0)
    assert results[18].reserve_floor_pct == pytest.approx(60.0)
    assert results[32].reserve_floor_pct == pytest.approx(20.0)

    # The fleet is up at the floor before the spell and stays there through it.
    for i in TIGHT:
        assert results[i].soc_p10_pct >= 60.0 - 0.5, (i, results[i].soc_p10_pct)
    # The reasons reach the Member Card.
    card = results[18].member_card
    assert card is not None and card.headline.startswith("Why is your battery at 60%")
    assert "60% chance of a price spike by" in card.reasons[0]
    assert results[17].member_card is None
