"""Fleet State and Fleet Plan: the planner's inputs and output (CONTEXT.md)."""

from pydantic import BaseModel

from gridtwin.fleet.models import DeviceState


class FleetState(BaseModel, frozen=True):
    discharge_headroom_mw: float
    charge_headroom_mw: float
    energy_above_floor_mwh: float = 0.0
    devices: list[DeviceState]  # non-stale Devices only
    stale_devices: int = 0  # Devices known to telemetry but excluded: stale or unhealthy
    # The non-stale Devices as one battery, for the LP (which never sees `devices`).
    capacity_mwh: float = 0.0
    energy_mwh: float = 0.0
    floor_mwh: float = 0.0
    max_power_mw: float = 0.0
    round_trip_efficiency: float = 1.0
    # Storm mode: the Dynamic Reserve Floor (0-1) for each upcoming interval, this one first
    # (empty = the Devices' own floor throughout). The LP charges ahead of a rising floor.
    reserve_floor_by_interval_pct: list[float] = []


class LpConfig(BaseModel, frozen=True):
    degradation_usd_per_mwh: float = 10.0  # per MWh discharged
    horizon_intervals: int = 96
    # lp_risk (ticket 10): value on stored energy before high-risk intervals.
    holdback_usd_per_mwh_h: float = 40.0
    holdback_lookahead_intervals: int = 4


class FleetPlan(BaseModel, frozen=True):
    target_mw: float  # +MW = discharge, -MW = charge, for this interval
    strategy: str
    # The LP's MW target for every interval of its horizon (this one first), and what its
    # prices came from (dam_spp | persistence | mixed). Empty for naive.
    horizon_mw: list[float] = []
    forecast_source: str = ""
    # lp_risk: the Risk Curve it planned on (spike probability per upcoming interval).
    risk_curve: list[float] = []
