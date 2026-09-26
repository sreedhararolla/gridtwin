"""Seam B: the `lp_risk` Strategy (pure, no IO): expected price = forecast + p(spike) x
spike premium, a soft SoC holdback ahead of high-risk intervals, and perfect foresight
still bounds it in the backtest."""

import random
from datetime import date

import pytest

from gridtwin.planner.backtest import backtest_day, execute, lp_risk_schedule
from gridtwin.planner.lp import (
    FleetAggregate,
    LpConfig,
    expected_prices,
    holdback_values,
    lp_strategy,
    schedule_value,
    solve,
    terminal_value,
)
from gridtwin.planner.models import FleetState

CONFIG = LpConfig(holdback_usd_per_mwh_h=40.0, holdback_lookahead_intervals=4)
FLEET = FleetAggregate(
    max_discharge_mw=20.0,
    max_charge_mw=20.0,
    capacity_mwh=78.4,
    floor_mwh=15.68,
    energy_mwh=39.2,
    round_trip_efficiency=0.9,
)


def test_expected_price_adds_the_spike_premium_only_where_the_curve_reaches():
    prices = expected_prices([30.0, 30.0, 30.0], [0.0, 0.5], 200.0)
    assert prices == [30.0, 130.0, 30.0]


def test_holdback_values_peak_risk_over_the_next_intervals():
    values = holdback_values([0.0, 0.0, 0.0, 0.0, 0.0, 0.5], CONFIG)
    assert values[0] == 0.0  # the risky interval is 5 ahead: outside the lookahead
    assert values[1] == pytest.approx(20.0)  # 40 $/MWh-h x 0.5
    assert values[5] == 0.0  # nothing after the last interval


def test_lp_risk_holds_energy_for_a_likely_spike_the_forecast_misses():
    """Forecast: an evening bump at interval 10 worth selling into. The Risk Curve says
    interval 12 will probably spike. lp spends the fleet at 10; lp_risk keeps it for 12."""
    forecast = [30.0] * 96
    forecast[10] = 150.0
    curve = [0.0] * 16
    curve[12] = 0.6
    end = terminal_value(forecast)
    lp = solve(forecast, FLEET, CONFIG, end)
    risk = solve(
        expected_prices(forecast, curve, 1000.0), FLEET, CONFIG, end, holdback_values(curve, CONFIG)
    )
    assert lp.target_mw[10] > 0 and lp.energy_mwh[11] < risk.energy_mwh[11]
    assert risk.target_mw[12] == pytest.approx(20.0)


def test_lp_strategy_with_a_risk_curve_is_lp_risk():
    state = FleetState(
        discharge_headroom_mw=20.0,
        charge_headroom_mw=20.0,
        devices=[],
        capacity_mwh=78.4,
        energy_mwh=39.2,
        floor_mwh=15.68,
        max_power_mw=20.0,
        round_trip_efficiency=0.9,
    )
    plan = lp_strategy(state, [30.0] * 96, CONFIG, "dam_spp+risk", [0.9] + [0.0] * 15, 500.0)
    assert plan.strategy == "lp_risk"
    assert plan.risk_curve[0] == 0.9
    assert plan.target_mw == pytest.approx(20.0)  # 30 + 0.9 x 500 now beats holding
    assert lp_strategy(state, [30.0] * 96, CONFIG, "dam_spp").strategy == "lp"


def test_without_a_risk_curve_lp_risk_matches_lp():
    rng = random.Random(10)
    forecast = [rng.uniform(10, 120) for _ in range(96)]
    actual = [p * rng.uniform(0.7, 1.3) for p in forecast]
    end = terminal_value(forecast)
    lp = execute(solve(forecast, FLEET, CONFIG, end).target_mw, FLEET)
    rolled = lp_risk_schedule(forecast, {}, FLEET, CONFIG, end)
    assert schedule_value(actual, rolled, FLEET.energy_mwh, CONFIG, end) == pytest.approx(
        schedule_value(actual, lp, FLEET.energy_mwh, CONFIG, end), rel=1e-3
    )


def test_perfect_foresight_bounds_lp_risk():
    rng = random.Random(12)
    for i in range(40):
        actual = [
            rng.uniform(500, 3000) if rng.random() < 0.05 else rng.uniform(5, 100)
            for _ in range(96)
        ]
        forecast = [p * rng.uniform(0.5, 1.5) for p in actual]
        risk = {t: ([rng.random() * 0.3 for _ in range(16)], 400.0) for t in range(96)}
        results = backtest_day(
            date(2026, 2, 1 + i % 28), actual, forecast, "dam_spp", FLEET, CONFIG, 90, 20, risk
        )
        values = {r.strategy: r.value_usd for r in results}
        assert set(values) == {"naive", "lp", "lp_risk", "perfect_foresight"}
        assert values["perfect_foresight"] >= values["lp_risk"] - 1e-4
        assert next(r for r in results if r.strategy == "lp_risk").forecast_source == (
            "dam_spp+risk"
        )
