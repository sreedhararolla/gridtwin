"""Device, Command and Ack: the pure domain's view of one simulated battery."""

from datetime import datetime

from pydantic import BaseModel


class DeviceState(BaseModel, frozen=True):
    device_id: str
    soc_pct: float  # 0..1, State of Charge
    energy_kwh: float
    max_power_kw: float
    round_trip_efficiency: float
    reserve_floor_pct: float


class Command(BaseModel, frozen=True):
    idempotency_key: str
    run_id: str
    interval_start: datetime
    device_id: str
    seq: int
    setpoint_mw: float  # +MW = discharge, -MW = charge
    expires_at: datetime


class Ack(BaseModel, frozen=True):
    idempotency_key: str
    device_id: str
    applied: bool
    delivered_mw: float
    soc_pct_after: float
    floor_violation: bool = False
