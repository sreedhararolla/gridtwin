"""Seam B: the LP planner and the strategy backtest (pure, no IO).

Property tests on seeded random price vectors and fleets: every LP solution respects SoC
dynamics, power limits, capacity and the Reserve Floor; perfect foresight is never beaten
by another Strategy; a 96-interval horizon solves inside the 200 ms budget.
"""

import random
import time
from datetime import date

import pytest

from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.planner.backtest import backtest_day, execute, fit_forecast, naive_schedule
from gridtwin.planner.lp import (
    INTERVAL_HOURS,
    FleetAggregate,
    LpConfig,
    lp_strategy,
    schedule_value,
    solve,
    terminal_value,
)
from gridtwin.planner.models import FleetState

CASES = 200
EPS = 1e-6
CONFIG = LpConfig()
FIXTURES = [
    "data/fixtures/rtm_spp_lz_houston_2025-12-10.csv",
    "data/fixtures/rtm_spp_lz_houston_2026-01-28.csv",
]


def random_prices(rng: random.Random, n: int) -> list[float]:
    """Mostly ordinary prices, some negative, some scarcity spikes."""
    prices = []
    for _ in range(n):
        roll = rng.random()
        if roll < 0.05:
            prices.append(rng.uniform(500, 5000))
        elif roll < 0.12:
            prices.append(rng.uniform(-50, 0))
        else:
            prices.append(rng.uniform(5, 120))
    return prices


def random_fleet(rng: random.Random) -> FleetAggregate:
    capacity = rng.uniform(1.0, 100.0)
    floor_pct = rng.uniform(0.0, 0.5)
    return FleetAggregate(
        max_discharge_mw=rng.uniform(0.1, 30.0),
        max_charge_mw=rng.uniform(0.1, 30.0),
        capacity_mwh=capacity,
        floor_mwh=capacity * floor_pct,
        energy_mwh=capacity * rng.choice([floor_pct, 1.0, rng.uniform(floor_pct, 1.0)]),
        round_trip_efficiency=rng.uniform(0.7, 1.0),
    )


def test_lp_solutions_respect_every_constraint():
    rng = random.Random(20260926)
    for _ in range(CASES):
        fleet = random_fleet(rng)
        prices = random_prices(rng, rng.randint(1, 100))
        schedule = solve(prices, fleet, CONFIG, terminal_value(prices))

        energy = fleet.energy_mwh
        for c, d, e in zip(
            schedule.charge_mw, schedule.discharge_mw, schedule.energy_mwh, strict=True
        ):
            assert -EPS <= c <= fleet.max_charge_mw + EPS
            assert -EPS <= d <= fleet.max_discharge_mw + EPS
            assert min(c, d) <= EPS  # never charges and discharges in the same interval
            energy += fleet.round_trip_efficiency * c * INTERVAL_HOURS - d * INTERVAL_HOURS
            assert e == pytest.approx(energy, abs=1e-5)  # SoC dynamics
            assert e >= fleet.floor_mwh - 1e-5  # Reserve Floor
            assert e <= fleet.capacity_mwh + 1e-5


def test_perfect_foresight_beats_every_strategy_on_random_days():
    rng = random.Random(7)
    for i in range(CASES):
        fleet = random_fleet(rng)
        n = rng.randint(92, 100)
        actual = random_prices(rng, n)
        forecast = [p * rng.uniform(0.5, 1.5) for p in actual]  # an imperfect forecast
        results = backtest_day(
            date(2026, 1, 1 + i % 28), actual, forecast, "dam_spp", fleet, CONFIG, 90.0, 20.0
        )
        values = {r.strategy: r.value_usd for r in results}
        for strategy, value in values.items():
            assert values["perfect_foresight"] >= value - 1e-4, strategy


@pytest.mark.parametrize("fixture_path", FIXTURES)
def test_perfect_foresight_beats_every_strategy_on_real_fixture_days(fixture_path: str):
    actual = [price for _, price in load_fixture_day("LZ_HOUSTON", fixture_path)]
    fleet = FleetAggregate(
        max_discharge_mw=20.0,
        max_charge_mw=20.0,
        capacity_mwh=78.4,
        floor_mwh=78.4 * 0.2,
        energy_mwh=78.4 * 0.5,
        round_trip_efficiency=0.9,
    )
    flat = [sum(actual) / len(actual)] * len(actual)
    results = backtest_day(date(2026, 1, 28), actual, flat, "dam_spp", fleet, CONFIG, 90.0, 20.0)
    values = {r.strategy: r.value_usd for r in results}
    assert values["perfect_foresight"] >= max(values.values()) - 1e-4
    assert values["perfect_foresight"] > 0


def test_executed_and_naive_schedules_never_leave_the_battery_limits():
    rng = random.Random(11)
    for _ in range(CASES):
        fleet = random_fleet(rng)
        prices = random_prices(rng, 96)
        targets = [rng.uniform(-50, 50) for _ in prices]
        for schedule in (execute(targets, fleet), naive_schedule(prices, fleet, 90.0, 20.0)):
            for e in schedule.energy_mwh:
                assert min(fleet.floor_mwh, fleet.energy_mwh) - EPS <= e
                assert e <= fleet.capacity_mwh + EPS


def test_96_interval_horizon_solves_under_200_ms():
    rng = random.Random(3)
    fleet = random_fleet(rng)
    prices = random_prices(rng, 96)
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        solve(prices, fleet, CONFIG, terminal_value(prices))
        timings.append((time.perf_counter() - started) * 1000)
    assert min(timings) < 200.0


def test_lp_holds_charge_into_a_forecast_spike():
    """A spike later in the horizon: the LP does not spend energy on ordinary prices now,
    and does discharge in the spike."""
    prices = [40.0] * 96
    prices[70] = 2000.0
    fleet = FleetAggregate(
        max_discharge_mw=20.0,
        max_charge_mw=20.0,
        capacity_mwh=78.4,
        floor_mwh=15.68,
        energy_mwh=39.2,
        round_trip_efficiency=0.9,
    )
    schedule = solve(prices, fleet, CONFIG, terminal_value(prices))
    assert all(t <= EPS for t in schedule.target_mw[:70])
    assert schedule.target_mw[70] == pytest.approx(20.0)


def test_lp_strategy_clips_to_this_intervals_headroom():
    # 10 Devices at 90% SoC; the planner sees aggregates only (with_reserve drops devices).
    state = FleetState(
        discharge_headroom_mw=0.05,
        charge_headroom_mw=0.0,
        devices=[],
        capacity_mwh=0.392,
        energy_mwh=0.3528,
        floor_mwh=0.0784,
        max_power_mw=0.1,
        round_trip_efficiency=0.9,
    )
    plan = lp_strategy(state, [3000.0] + [10.0] * 95, CONFIG, "dam_spp")
    assert plan.strategy == "lp"
    assert plan.forecast_source == "dam_spp"
    assert len(plan.horizon_mw) == 96
    assert plan.target_mw == pytest.approx(0.05)  # wants 0.1 MW, headroom allows 0.05


def test_value_is_the_lp_objective():
    rng = random.Random(5)
    fleet = random_fleet(rng)
    prices = random_prices(rng, 48)
    end_value = terminal_value(prices)
    optimal = solve(prices, fleet, CONFIG, end_value)
    replayed = execute(optimal.target_mw, fleet)
    assert schedule_value(prices, replayed, fleet.energy_mwh, CONFIG, end_value) == pytest.approx(
        schedule_value(prices, optimal, fleet.energy_mwh, CONFIG, end_value), abs=1e-3
    )


def test_fit_forecast_pads_and_trims_for_dst_days():
    assert fit_forecast([1.0, 2.0], 4) == [1.0, 2.0, 2.0, 2.0]
    assert fit_forecast([1.0, 2.0, 3.0], 2) == [1.0, 2.0]
    assert fit_forecast([], 3) == []
