"""Seam A: the `lp_risk` Strategy in a Replay Run on the real spike day. Each interval's
plan reads the Risk Curve stored for that decision time and says so in its audit trail;
with no stored curves it plans as `lp`."""

from datetime import timedelta

import duckdb
import pandas as pd
import pytest

from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.risk.features import HORIZON_INTERVALS
from gridtwin.risk.paths import predictions_path
from gridtwin.settings import settings
from tests.test_scenario_lp import PEAK_INTERVAL, SPIKE_DAY_FIXTURE, dam_cache, run  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def risk_curves(dam_cache):  # noqa: F811
    """Stored Risk Curves for the spike day: 60% spike risk at the peak, 1% elsewhere."""
    rows = load_fixture_day(settings.settlement_point, SPIKE_DAY_FIXTURE)
    peak = rows[PEAK_INTERVAL][0]
    records = []
    for decision, price in rows:
        for lead in range(HORIZON_INTERVALS):
            target = decision + timedelta(minutes=15 * lead)
            records.append(
                {
                    "decision_utc": decision,
                    "target_utc": target,
                    "lead": lead,
                    "rt_price": price,
                    "spike": int(price > 165.0),
                    "p_spike": 0.6 if target == peak else 0.01,
                    "p_climatology": 0.01,
                    "threshold_usd": 165.0,
                    "premium_usd": 500.0,
                    "provenance": "walk-forward",
                    "test_month": "2026-01",
                    "settlement_point": settings.settlement_point,
                }
            )
    df = pd.DataFrame(records)  # noqa: F841 (read by duckdb below)
    path = predictions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    duckdb.sql("SELECT * FROM df").write_parquet(str(path))


async def test_lp_risk_plans_on_the_stored_risk_curve(risk_curves):
    outcome = await run("lp_risk", "scenario-lp-risk-spike")
    assert outcome.report.intervals == 96
    assert outcome.report.reserve_violations == 0
    assert outcome.report.within_tolerance_pct >= 95.0
    assert all(r.strategy == "lp_risk" for r in outcome.results)
    assert all(r.forecast_source.endswith("+risk") for r in outcome.results)
    assert outcome.results[PEAK_INTERVAL].delivered_mw > 1.0


async def test_lp_risk_without_stored_curves_plans_as_lp(dam_cache):  # noqa: F811
    outcome = await run("lp_risk", "scenario-lp-risk-no-curves")
    assert outcome.report.reserve_violations == 0
    assert all(r.strategy == "lp" for r in outcome.results)
