"""Device, Command, Ack and Heartbeat: the pure domain's view of one simulated battery."""

from datetime import datetime

from pydantic import BaseModel


class DeviceState(BaseModel, frozen=True):
    device_id: str
    soc_pct: float  # 0..1, State of Charge
    energy_kwh: float
    max_power_kw: float
    round_trip_efficiency: float
    reserve_floor_pct: float
    shard_id: str = ""


class FleetConfig(BaseModel, frozen=True):
    """Everything needed to build the same simulated fleet on every process, so a Replay
    Run's input carries this small config instead of 2,000 device records."""

    device_count: int
    shard_count: int
    energy_kwh: float
    max_power_kw: float
    round_trip_efficiency: float
    reserve_floor_pct: float
    initial_soc_pct: float
    response_noise_pct: float = 0.0  # std-dev of delivered/setpoint, e.g. 0.02 = 2%
    fault_rate: float = 0.0  # probability a Device fails to act on a Command
    seed: int = 0


class ShardReset(BaseModel, frozen=True):
    """Sent to a shard at the start of a Replay Run: these are your Devices now."""

    run_id: str
    shard_id: str
    devices: list[DeviceState]
    response_noise_pct: float
    fault_rate: float
    seed: int


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


class Heartbeat(BaseModel, frozen=True):
    """Periodic Device telemetry (CONTEXT.md). `sent_at` is wall time; staleness is judged
    against it. The full DeviceState rides along so Fleet State is rebuilt from telemetry."""

    run_id: str
    state: DeviceState
    power_mw: float
    healthy: bool
    sent_at: datetime
