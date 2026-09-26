"""Fleet State and Fleet Plan: the planner's inputs and output (CONTEXT.md)."""

from pydantic import BaseModel

from gridtwin.fleet.models import DeviceState


class FleetState(BaseModel, frozen=True):
    discharge_headroom_mw: float
    charge_headroom_mw: float
    devices: list[DeviceState]


class FleetPlan(BaseModel, frozen=True):
    target_mw: float  # +MW = discharge, -MW = charge, for this interval
    strategy: str
