"""Offline strategy backtest on the fleet aggregate: pure, no IO.

Each day starts from the same energy. `naive` reacts to each interval's RT price, `lp`
plans the day on a price forecast and executes it, and `perfect_foresight` plans on the
actual RT prices. Every schedule is settled at the actual RT prices with the same value
function the LP maximises, so perfect foresight is an upper bound on every day.
"""

from collections.abc import Callable
from datetime import date

from pydantic import BaseModel

from gridtwin.planner.lp import (
    INTERVAL_HOURS,
    FleetAggregate,
    LpConfig,
    Schedule,
    schedule_value,
    solve,
    terminal_value,
)

STRATEGIES = ("naive", "lp", "perfect_foresight")
DAYS_PER_MONTH = 365.25 / 12


class DayResult(BaseModel, frozen=True):
    day: date
    strategy: str
    value_usd: float
    usd_per_mw_month: float  # this day's value, as if every day of a month were like it
    discharged_mwh: float
    charged_mwh: float
    intervals: int
    forecast_source: str  # what `lp` planned on: dam_spp | persistence


def headroom(fleet: FleetAggregate, energy_mwh: float) -> tuple[float, float]:
    """(discharge MW, charge MW) available this interval, as the device model computes it."""
    discharge = min(fleet.max_discharge_mw, max(energy_mwh - fleet.floor_mwh, 0.0) / INTERVAL_HOURS)
    charge = min(fleet.max_charge_mw, max(fleet.capacity_mwh - energy_mwh, 0.0) / INTERVAL_HOURS)
    return discharge, charge


def _run(fleet: FleetAggregate, policy: Callable[[int, float, float], float | None]) -> Schedule:
    """Step the aggregate battery: `policy(t, max_discharge, max_charge)` gives the net MW
    target (None = done), which is clipped to headroom."""
    energy = fleet.energy_mwh
    charge_mw: list[float] = []
    discharge_mw: list[float] = []
    energy_mwh: list[float] = []
    t = 0
    while True:
        max_d, max_c = headroom(fleet, energy)
        target = policy(t, max_d, max_c)
        if target is None:
            break
        d = min(max(target, 0.0), max_d)
        c = min(max(-target, 0.0), max_c)
        energy += fleet.round_trip_efficiency * c * INTERVAL_HOURS - d * INTERVAL_HOURS
        charge_mw.append(c)
        discharge_mw.append(d)
        energy_mwh.append(energy)
        t += 1
    return Schedule(charge_mw=charge_mw, discharge_mw=discharge_mw, energy_mwh=energy_mwh)


def execute(targets: list[float], fleet: FleetAggregate) -> Schedule:
    """Run net MW targets through the aggregate battery, clipped to headroom."""
    return _run(fleet, lambda t, _d, _c: targets[t] if t < len(targets) else None)


def naive_schedule(
    prices: list[float], fleet: FleetAggregate, discharge_usd: float, charge_usd: float
) -> Schedule:
    """The naive Strategy, interval by interval: full discharge at/above the high threshold,
    full charge at/below the low one (planner/naive.py on the aggregate)."""

    def policy(t: int, max_d: float, max_c: float) -> float | None:
        if t >= len(prices):
            return None
        price = prices[t]
        return max_d if price >= discharge_usd else -max_c if price <= charge_usd else 0.0

    return _run(fleet, policy)


def backtest_day(
    day: date,
    actual: list[float],
    forecast: list[float],
    forecast_source: str,
    fleet: FleetAggregate,
    config: LpConfig,
    discharge_usd: float,
    charge_usd: float,
) -> list[DayResult]:
    """All three Strategies on one day. Remaining energy is valued at the forecast's median
    for every Strategy alike (a price known before the day starts)."""
    end_value = terminal_value(forecast)
    schedules = {
        "naive": naive_schedule(actual, fleet, discharge_usd, charge_usd),
        "lp": execute(solve(forecast, fleet, config, end_value).target_mw, fleet),
        "perfect_foresight": solve(actual, fleet, config, end_value),
    }
    fleet_mw = max(fleet.max_discharge_mw, 1e-9)
    results = []
    for strategy, schedule in schedules.items():
        value = schedule_value(actual, schedule, fleet.energy_mwh, config, end_value)
        results.append(
            DayResult(
                day=day,
                strategy=strategy,
                value_usd=value,
                usd_per_mw_month=value / fleet_mw * DAYS_PER_MONTH,
                discharged_mwh=sum(schedule.discharge_mw) * INTERVAL_HOURS,
                charged_mwh=sum(schedule.charge_mw) * INTERVAL_HOURS,
                intervals=len(actual),
                forecast_source=forecast_source,
            )
        )
    return results


class StrategySummary(BaseModel, frozen=True):
    strategy: str
    days: int
    value_usd: float
    usd_per_mw_month: float  # total value / fleet MW / months in the window
    discharged_mwh: float
    share_of_perfect_foresight_pct: float


class BacktestReport(BaseModel, frozen=True):
    settlement_point: str
    start_day: date | None
    end_day: date | None
    fleet_mw: float
    fleet_mwh: float
    start_soc_pct: float
    degradation_usd_per_mwh: float
    naive_discharge_threshold_usd: float
    naive_charge_threshold_usd: float
    lp_solve_ms_p50: float  # one 96-interval horizon on the fleet aggregate
    lp_solve_ms_max: float
    summary: list[StrategySummary]
    days: list[DayResult]


def summarize(days: list[DayResult], fleet_mw: float) -> list[StrategySummary]:
    totals = {s: [r for r in days if r.strategy == s] for s in STRATEGIES}
    best = sum(r.value_usd for r in totals["perfect_foresight"])
    summary = []
    for strategy, rows in totals.items():
        value = sum(r.value_usd for r in rows)
        months = len(rows) / DAYS_PER_MONTH
        summary.append(
            StrategySummary(
                strategy=strategy,
                days=len(rows),
                value_usd=value,
                usd_per_mw_month=value / max(fleet_mw, 1e-9) / months if months else 0.0,
                discharged_mwh=sum(r.discharged_mwh for r in rows),
                share_of_perfect_foresight_pct=100.0 * value / best if best > 0 else 0.0,
            )
        )
    return summary


def fit_forecast(forecast: list[float], length: int) -> list[float]:
    """Trim or pad (with the last value) a forecast to a day's interval count (DST days)."""
    if not forecast:
        return []
    return (forecast + [forecast[-1]] * length)[:length]
