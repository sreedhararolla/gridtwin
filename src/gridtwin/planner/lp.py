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

from gridtwin.planner.models import FleetPlan, FleetState

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


class LpConfig(BaseModel, frozen=True):
    degradation_usd_per_mwh: float = 10.0  # per MWh discharged
    horizon_intervals: int = 96


def terminal_value(prices: list[float]) -> float:
    """$/MWh for energy left at the end of the horizon: the median price, never negative."""
    return max(float(np.median(prices)), 0.0) if prices else 0.0


def solve(
    prices: list[float], fleet: FleetAggregate, config: LpConfig, end_value: float
) -> Schedule:
    """The optimal schedule for `prices` (one per Market Interval)."""
    n = len(prices)
    if n == 0:
        return Schedule(charge_mw=[], discharge_mw=[], energy_mwh=[])
    dt = INTERVAL_HOURS
    p = np.asarray(prices, dtype=float)
    # Variables: [c_0..c_{n-1}, d_0..d_{n-1}, e_0..e_{n-1}]; linprog minimises.
    cost = np.concatenate(
        [
            (p + CHARGE_WEAR_USD_PER_MWH) * dt,
            -(p - config.degradation_usd_per_mwh) * dt,
            np.zeros(n),
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
    bounds = (
        [(0.0, max(fleet.max_charge_mw, 0.0))] * n
        + [(0.0, max(fleet.max_discharge_mw, 0.0))] * n
        + [(floor, capacity)] * n
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
    """The live Fleet State as one battery. Power limits are this interval's headroom (so
    the Reallocation reserve is respected); energy comes from the non-stale Devices."""
    devices = fleet_state.devices
    capacity = sum(d.energy_kwh for d in devices) / 1000.0
    energy = sum(d.energy_kwh * d.soc_pct for d in devices) / 1000.0
    floor = sum(d.energy_kwh * d.reserve_floor_pct for d in devices) / 1000.0
    rte = (
        sum(d.round_trip_efficiency * d.energy_kwh for d in devices) / (capacity * 1000.0)
        if capacity > 0
        else 1.0
    )
    return FleetAggregate(
        max_discharge_mw=sum(d.max_power_kw for d in devices) / 1000.0,
        max_charge_mw=sum(d.max_power_kw for d in devices) / 1000.0,
        capacity_mwh=capacity,
        floor_mwh=floor,
        energy_mwh=energy,
        round_trip_efficiency=rte,
    )


def lp_strategy(
    fleet_state: FleetState,
    forecast_usd_per_mwh: list[float],
    config: LpConfig,
    strategy: str = "lp",
) -> FleetPlan:
    """Rolling horizon: solve over the forecast from this interval on, act on the first
    interval only, and clip it to this interval's headroom."""
    horizon = forecast_usd_per_mwh[: config.horizon_intervals]
    if not horizon or not fleet_state.devices:
        return FleetPlan(target_mw=0.0, strategy=strategy)
    schedule = solve(horizon, aggregate_of(fleet_state), config, terminal_value(horizon))
    target = schedule.target_mw[0]
    target = min(max(target, -fleet_state.charge_headroom_mw), fleet_state.discharge_headroom_mw)
    return FleetPlan(target_mw=target, strategy=strategy)
