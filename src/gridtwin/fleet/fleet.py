"""Pure fleet construction and fleet-wide summaries: which Device lives on which Shard,
Fleet State from telemetry, and the SoC band the Live tab draws."""

from datetime import datetime

from gridtwin.fleet.device import aggregate_headroom
from gridtwin.fleet.models import DeviceState, FleetConfig, Heartbeat
from gridtwin.planner.models import FleetState


def shard_ids(shard_count: int) -> list[str]:
    return [f"shard-{i}" for i in range(shard_count)]


def build_fleet(config: FleetConfig) -> dict[str, list[DeviceState]]:
    """Devices in contiguous blocks per shard: battery-0..99 on shard-0, and so on."""
    shards = shard_ids(config.shard_count)
    per_shard = -(-config.device_count // config.shard_count)  # ceil division
    fleet: dict[str, list[DeviceState]] = {shard: [] for shard in shards}
    for i in range(config.device_count):
        shard = shards[i // per_shard]
        fleet[shard].append(
            DeviceState(
                device_id=f"battery-{i}",
                soc_pct=config.initial_soc_pct,
                energy_kwh=config.energy_kwh,
                max_power_kw=config.max_power_kw,
                round_trip_efficiency=config.round_trip_efficiency,
                reserve_floor_pct=config.reserve_floor_pct,
                shard_id=shard,
            )
        )
    return fleet


def group_by_shard(
    setpoints: dict[str, float], devices: list[DeviceState]
) -> dict[str, dict[str, float]]:
    shard_of = {d.device_id: d.shard_id for d in devices}
    batches: dict[str, dict[str, float]] = {}
    for device_id, setpoint_mw in setpoints.items():
        batches.setdefault(shard_of[device_id], {})[device_id] = setpoint_mw
    return batches


def is_stale(heartbeat: Heartbeat, now: datetime, stale_after_seconds: float) -> bool:
    return (now - heartbeat.sent_at).total_seconds() > stale_after_seconds


def fleet_state_from_telemetry(
    heartbeats: list[Heartbeat], now: datetime, stale_after_seconds: float
) -> FleetState:
    """Fleet State: aggregate headroom of non-stale, healthy Devices only."""
    devices = [
        hb.state for hb in heartbeats if hb.healthy and not is_stale(hb, now, stale_after_seconds)
    ]
    discharge_mw, charge_mw = aggregate_headroom(devices)
    energy_mwh = sum(
        max(d.soc_pct - d.reserve_floor_pct, 0.0) * d.energy_kwh / 1000.0 for d in devices
    )
    return FleetState(
        discharge_headroom_mw=discharge_mw,
        charge_headroom_mw=charge_mw,
        energy_above_floor_mwh=energy_mwh,
        devices=devices,
    )


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = q * (len(sorted_values) - 1)
    lo = int(index)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (index - lo)


def soc_band(devices: list[DeviceState]) -> tuple[float, float, float]:
    """(p10, median, p90) SoC in percent, 0-100."""
    values = sorted(d.soc_pct * 100.0 for d in devices)
    return _percentile(values, 0.10), _percentile(values, 0.50), _percentile(values, 0.90)
