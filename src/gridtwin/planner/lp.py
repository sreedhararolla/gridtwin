"""The `lp` and `perfect_foresight` Strategies: a linear program on the fleet aggregate,
solved with HiGHS via scipy.

Maximise value at the settlement point over the horizon:

    sum_t price_t * (d_t - c_t) * dt  -  degradation * d_t * dt  -  CHARGE_WEAR * c_t * dt
      + terminal_value * (e_end - e_0)

subject to the same physics as the device model (fleet/device.py), where the whole
round-trip loss is taken on charge:

    e_t = e_{t-1} + rte * c_t * dt - d_t * dt,   floor <= e_t <= capacity,
    0 <= c_t <= max charge MW,  0 <= d_t <= max discharge MW.

`lp` solves this on a price forecast (DAM SPP baseline); `perfect_foresight` solves it on
the actual RT prices, which makes it an upper bound for any schedule the fleet could run.
Remaining energy is valued at `terminal_value` so the planner does not dump the fleet
at the end of the horizon just because the horizon ends.
"""

import numpy as np
from pydantic import BaseModel
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import csr_matrix, hstack, identity, vstack

from gridtwin.planner.models import FleetPlan, FleetState, LpConfig

INTERVAL_HOURS = 0.25
# A tiny wear cost on charging too, so the solver never charges and discharges in the
# same interval (a net Fleet Plan target could not represent that).
CHARGE_WEAR_USD_PER_MWH = 0.01
SIMULTANEOUS_TOL_MW = 1e-6


class FleetAggregate(BaseModel, frozen=True):
    """The fleet as one battery: what the LP plans against."""

    max_discharge_mw: float
    max_charge_mw: float
    capacity_mwh: float
    floor_mwh: float
    energy_mwh: float  # at the start of the horizon
    round_trip_efficiency: float


class Schedule(BaseModel, frozen=True):
    """A planned (or simulated) trajectory: per-interval charge/discharge MW and the energy
    after each interval."""

    charge_mw: list[float]
    discharge_mw: list[float]
    energy_mwh: list[float]

    @property
    def target_mw(self) -> list[float]:
        return [d - c for c, d in zip(self.charge_mw, self.discharge_mw, strict=True)]


def terminal_value(prices: list[float]) -> float:
    """$/MWh for energy left at the end of the horizon: the median price, never negative."""
    return max(float(np.median(prices)), 0.0) if prices else 0.0


def solve(
    prices: list[float],
    fleet: FleetAggregate,
    config: LpConfig,
    end_value: float,
    holdback_usd_per_mwh_h: list[float] | None = None,
    floor_mwh_by_interval: list[float] | None = None,
) -> Schedule:
    """The optimal schedule for `prices` (one per Market Interval). `holdback_usd_per_mwh_h`
    (lp_risk) is a planning-only value per MWh stored through each interval: a soft SoC
    holdback. It is not part of the settled value. `floor_mwh_by_interval` (Storm mode) is a
    Dynamic Reserve Floor the energy after each interval must meet (beyond it, the fleet's
    floor); a raised floor the fleet cannot charge up to in time is met as far as it can be."""
    n = len(prices)
    if n == 0:
        return Schedule(charge_mw=[], discharge_mw=[], energy_mwh=[])
    dt = INTERVAL_HOURS
    p = np.asarray(prices, dtype=float)
    holdback = np.zeros(n)
    if holdback_usd_per_mwh_h:
        holdback[: len(holdback_usd_per_mwh_h)] = holdback_usd_per_mwh_h[:n]
    # Variables: [c_0..c_{n-1}, d_0..d_{n-1}, e_0..e_{n-1}]; linprog minimises.
    cost = np.concatenate(
        [
            (p + CHARGE_WEAR_USD_PER_MWH) * dt,
            -(p - config.degradation_usd_per_mwh) * dt,
            -holdback * dt,
        ]
    )
    cost[-1] -= end_value

    # e_t - e_{t-1} - rte*dt*c_t + dt*d_t = 0 (e_{-1} = energy at the start)
    shift = csr_matrix((np.ones(n - 1), (np.arange(1, n), np.arange(n - 1))), shape=(n, n))
    a_eq = hstack(
        [
            -fleet.round_trip_efficiency * dt * identity(n),
            dt * identity(n),
            identity(n) - shift,
        ],
        format="csr",
    )
    b_eq = np.zeros(n)
    b_eq[0] = fleet.energy_mwh

    # A fleet that starts below the floor may not be pushed further below it.
    floor = min(fleet.floor_mwh, fleet.energy_mwh)
    capacity = max(fleet.capacity_mwh, fleet.energy_mwh)
    energy_bounds = [(floor, capacity)] * n
    if floor_mwh_by_interval:
        step_mwh = fleet.round_trip_efficiency * max(fleet.max_charge_mw, 0.0) * dt
        energy_bounds = [
            (
                max(floor, min(dynamic, fleet.energy_mwh + step_mwh * (t + 1), capacity))
                if dynamic > fleet.floor_mwh
                else floor,
                capacity,
            )
            for t, dynamic in enumerate(floor_mwh_by_interval[:n])
        ] + [(floor, capacity)] * max(n - len(floor_mwh_by_interval), 0)
    bounds = (
        [(0.0, max(fleet.max_charge_mw, 0.0))] * n
        + [(0.0, max(fleet.max_discharge_mw, 0.0))] * n
        + energy_bounds
    )
    result = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not result.success:
        raise RuntimeError(f"LP failed: {result.message}")
    x = result.x
    if np.any(np.minimum(x[:n], x[n : 2 * n]) > SIMULTANEOUS_TOL_MW):
        x = _solve_exclusive(cost, a_eq, b_eq, bounds, n)
    return Schedule(
        charge_mw=[float(v) for v in x[:n]],
        discharge_mw=[float(v) for v in x[n : 2 * n]],
        energy_mwh=[float(v) for v in x[2 * n :]],
    )


def _solve_exclusive(
    cost: np.ndarray,
    a_eq: csr_matrix,
    b_eq: np.ndarray,
    bounds: list[tuple[float, float]],
    n: int,
) -> np.ndarray:
    """Deeply negative prices can make burning energy on round-trip losses pay, so the LP
    charges and discharges in the same interval, which one net target cannot do. Re-solve
    with a binary per interval (charge xor discharge). Rare on real prices."""
    max_c = np.array([hi for _, hi in bounds[:n]])
    max_d = np.array([hi for _, hi in bounds[n : 2 * n]])
    eye = identity(n, format="csr")
    zeros = csr_matrix((n, n))
    # c_t - max_c * u_t <= 0 ;  d_t + max_d * u_t <= max_d
    a_ub = vstack(
        [
            hstack([eye, zeros, zeros, -csr_matrix(np.diag(max_c))]),
            hstack([zeros, eye, zeros, csr_matrix(np.diag(max_d))]),
        ],
        format="csr",
    )
    a_eq_u = hstack([a_eq, csr_matrix((n, n))], format="csr")
    lo = np.array([lo for lo, _ in bounds] + [0.0] * n)
    hi = np.array([hi for _, hi in bounds] + [1.0] * n)
    result = milp(
        np.concatenate([cost, np.zeros(n)]),
        constraints=[
            LinearConstraint(a_eq_u, b_eq, b_eq),
            LinearConstraint(a_ub, -np.inf, np.concatenate([np.zeros(n), max_d])),
        ],
        integrality=np.concatenate([np.zeros(3 * n), np.ones(n)]),
        bounds=Bounds(lo, hi),
    )
    if not result.success:
        raise RuntimeError(f"MILP failed: {result.message}")
    return result.x[: 3 * n]


def schedule_value(
    prices: list[float],
    schedule: Schedule,
    start_energy_mwh: float,
    config: LpConfig,
    end_value: float,
) -> float:
    """Value ($) of a schedule settled at `prices`: exactly the LP's objective, so the
    perfect-foresight solve is an upper bound for every feasible schedule."""
    dt = INTERVAL_HOURS
    value = 0.0
    for price, c, d in zip(prices, schedule.charge_mw, schedule.discharge_mw, strict=True):
        value += price * (d - c) * dt
        value -= config.degradation_usd_per_mwh * d * dt + CHARGE_WEAR_USD_PER_MWH * c * dt
    end_energy = schedule.energy_mwh[-1] if schedule.energy_mwh else start_energy_mwh
    return value + end_value * (end_energy - start_energy_mwh)


def aggregate_of(fleet_state: FleetState) -> FleetAggregate:
    """The live Fleet State (non-stale Devices) as one battery. The plan's first interval
    is clipped to headroom afterwards, which respects the Reallocation reserve."""
    return FleetAggregate(
        max_discharge_mw=fleet_state.max_power_mw,
        max_charge_mw=fleet_state.max_power_mw,
        capacity_mwh=fleet_state.capacity_mwh,
        floor_mwh=fleet_state.floor_mwh,
        energy_mwh=fleet_state.energy_mwh,
        round_trip_efficiency=fleet_state.round_trip_efficiency,
    )


def expected_prices(
    forecast: list[float], p_spike: list[float], spike_premium_usd: float
) -> list[float]:
    """lp_risk's price: forecast + p(spike) x mean spike premium, where the Risk Curve
    covers the horizon (it is shorter than the plan; beyond it the forecast stands)."""
    return [
        price + (p_spike[t] * spike_premium_usd if t < len(p_spike) else 0.0)
        for t, price in enumerate(forecast)
    ]


def holdback_values(p_spike: list[float], config: LpConfig) -> list[float]:
    """The soft SoC holdback: stored energy is worth `holdback_usd_per_mwh_h` x the peak
    spike probability over the next `holdback_lookahead_intervals`, so the plan keeps
    charge ahead of high-risk intervals without a hard constraint."""
    k = config.holdback_lookahead_intervals
    return [
        config.holdback_usd_per_mwh_h * max(p_spike[t + 1 : t + 1 + k], default=0.0)
        for t in range(len(p_spike))
    ]


def lp_strategy(
    fleet_state: FleetState,
    forecast_usd_per_mwh: list[float],
    config: LpConfig,
    forecast_source: str = "",
    p_spike: list[float] | None = None,
    spike_premium_usd: float = 0.0,
) -> FleetPlan:
    """Rolling horizon: solve over the forecast from this interval on, act on the first
    interval only, and clip it to this interval's headroom. With a Risk Curve (`p_spike`)
    this is the `lp_risk` Strategy."""
    strategy = "lp_risk" if p_spike is not None else "lp"
    horizon = forecast_usd_per_mwh[: config.horizon_intervals]
    if not horizon or fleet_state.capacity_mwh <= 0:
        return FleetPlan(target_mw=0.0, strategy=strategy, forecast_source=forecast_source)
    end_value = terminal_value(horizon)
    holdback = None
    if p_spike is not None:
        horizon = expected_prices(horizon, p_spike, spike_premium_usd)
        holdback = holdback_values(p_spike, config)
    floors = [pct * fleet_state.capacity_mwh for pct in fleet_state.reserve_floor_by_interval_pct]
    schedule = solve(
        horizon, aggregate_of(fleet_state), config, end_value, holdback, floors or None
    )
    target = schedule.target_mw[0]
    target = min(max(target, -fleet_state.charge_headroom_mw), fleet_state.discharge_headroom_mw)
    return FleetPlan(
        target_mw=target,
        strategy=strategy,
        horizon_mw=[round(mw, 3) for mw in schedule.target_mw],
        forecast_source=forecast_source,
        risk_curve=[round(p, 4) for p in p_spike or []],
    )
