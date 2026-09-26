"""Fleet State and Fleet Plan: the planner's inputs and output (CONTEXT.md)."""

from pydantic import BaseModel

from gridtwin.fleet.models import DeviceState


class FleetState(BaseModel, frozen=True):
    discharge_headroom_mw: float
    charge_headroom_mw: float
    energy_above_floor_mwh: float = 0.0
    devices: list[DeviceState]  # non-stale Devices only
    stale_devices: int = 0  # Devices known to telemetry but excluded: stale or unhealthy


class FleetPlan(BaseModel, frozen=True):
    target_mw: float  # +MW = discharge, -MW = charge, for this interval
    strategy: str
