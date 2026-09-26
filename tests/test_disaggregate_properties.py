"""Seam B property test: over thousands of seeded random fleets and targets, disaggregation
never asks a Device for more than its available power and never plans it below the
Reserve Floor - and the device model, even with response noise, never crosses it."""

import random
from datetime import UTC, datetime, timedelta

from gridtwin.fleet.device import INTERVAL_HOURS, apply_command, headroom_mw
from gridtwin.fleet.disaggregate import disaggregate
from gridtwin.fleet.models import Command, DeviceState

CASES = 2000
EPS = 1e-9
NOW = datetime(2026, 1, 28, 0, 0, tzinfo=UTC)


def random_device(rng: random.Random, i: int) -> DeviceState:
    floor = rng.uniform(0.0, 0.6)
    # Bias some devices to sit exactly at/near the floor or full, the edge cases.
    soc = rng.choice([floor, 1.0, rng.uniform(0.0, 1.0), floor + rng.uniform(0, 1e-6)])
    return DeviceState(
        device_id=f"d{i}",
        soc_pct=min(max(soc, 0.0), 1.0),
        energy_kwh=rng.uniform(5.0, 60.0),
        max_power_kw=rng.uniform(1.0, 25.0),
        round_trip_efficiency=rng.uniform(0.8, 1.0),
        reserve_floor_pct=floor,
    )


def test_disaggregation_respects_power_and_floor_for_random_fleets():
    rng = random.Random(20260928)
    for _ in range(CASES):
        devices = [random_device(rng, i) for i in range(rng.randint(1, 40))]
        fleet_discharge = sum(headroom_mw(d)[0] for d in devices)
        fleet_charge = sum(headroom_mw(d)[1] for d in devices)
        target_mw = rng.uniform(-2.0, 2.0) * max(fleet_discharge, fleet_charge, 1e-3)

        setpoints = disaggregate(target_mw, devices)

        assert abs(sum(setpoints.values())) <= abs(target_mw) + EPS
        for device in devices:
            setpoint = setpoints[device.device_id]
            discharge_mw, charge_mw = headroom_mw(device)
            if setpoint >= 0:
                assert setpoint <= discharge_mw + EPS
                assert setpoint <= device.max_power_kw / 1000.0 + EPS
                planned_soc = device.soc_pct - setpoint * 1000.0 * INTERVAL_HOURS / (
                    device.energy_kwh
                )
                if device.soc_pct < device.reserve_floor_pct:
                    assert setpoint == 0.0  # already below the floor: never discharged
                else:
                    assert planned_soc >= device.reserve_floor_pct - EPS
            else:
                assert -setpoint <= charge_mw + EPS
                assert -setpoint <= device.max_power_kw / 1000.0 + EPS


def test_device_never_crosses_floor_even_with_response_noise():
    rng = random.Random(7)
    for i in range(CASES):
        device = random_device(rng, i)
        setpoint = rng.uniform(-0.05, 0.05)
        command = Command(
            idempotency_key=f"run:{NOW.isoformat()}:{device.device_id}:1",
            run_id="run",
            interval_start=NOW,
            device_id=device.device_id,
            seq=1,
            setpoint_mw=setpoint,
            expires_at=NOW + timedelta(minutes=15),
        )
        new_state, ack = apply_command(device, command, response_factor=rng.gauss(1.0, 0.1))
        assert ack.floor_violation is False
        assert new_state.soc_pct >= min(device.reserve_floor_pct, device.soc_pct) - EPS
        if ack.delivered_mw > 0:
            assert new_state.soc_pct >= device.reserve_floor_pct - EPS
        assert new_state.soc_pct <= 1.0 + EPS
