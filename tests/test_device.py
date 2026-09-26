from datetime import UTC, datetime, timedelta

from gridtwin.fleet.device import aggregate_headroom, apply_command, headroom_mw
from gridtwin.fleet.models import Command, DeviceState

NOW = datetime(2025, 12, 10, 12, 0, tzinfo=UTC)


def make_device(soc_pct: float = 0.5) -> DeviceState:
    return DeviceState(
        device_id="battery-0",
        soc_pct=soc_pct,
        energy_kwh=39.2,
        max_power_kw=10.0,
        round_trip_efficiency=0.9,
        reserve_floor_pct=0.20,
    )


def make_command(device_id: str, setpoint_mw: float, seq: int = 1) -> Command:
    return Command(
        idempotency_key=f"run:{NOW.isoformat()}:{device_id}:{seq}",
        run_id="run",
        interval_start=NOW,
        device_id=device_id,
        seq=seq,
        setpoint_mw=setpoint_mw,
        expires_at=NOW + timedelta(minutes=15),
    )


def test_headroom_respects_floor_and_power_limit():
    device = make_device(soc_pct=0.5)
    discharge_mw, charge_mw = headroom_mw(device)
    # 0.30 * 39.2 kWh above floor over 0.25h = 47.04 kW, capped at the 10 kW power limit.
    assert discharge_mw == 10.0 / 1000.0
    assert charge_mw == 10.0 / 1000.0


def test_discharge_never_crosses_reserve_floor():
    device = make_device(soc_pct=0.21)
    command = make_command(device.device_id, setpoint_mw=1.0)  # absurdly large ask
    new_state, ack = apply_command(device, command)
    assert new_state.soc_pct >= device.reserve_floor_pct - 1e-9
    assert ack.floor_violation is False
    assert ack.applied is True


def test_charge_never_exceeds_full():
    device = make_device(soc_pct=0.99)
    command = make_command(device.device_id, setpoint_mw=-1.0)
    new_state, ack = apply_command(device, command)
    assert new_state.soc_pct <= 1.0 + 1e-9
    assert ack.delivered_mw <= 0.0


def test_idle_setpoint_delivers_nothing():
    device = make_device(soc_pct=0.5)
    command = make_command(device.device_id, setpoint_mw=0.0)
    new_state, ack = apply_command(device, command)
    assert ack.delivered_mw == 0.0
    assert new_state.soc_pct == device.soc_pct


def test_aggregate_headroom_sums_devices():
    devices = [make_device(0.5), make_device(0.5)]
    discharge_total, charge_total = aggregate_headroom(devices)
    single_discharge, single_charge = headroom_mw(devices[0])
    assert discharge_total == single_discharge * 2
    assert charge_total == single_charge * 2
