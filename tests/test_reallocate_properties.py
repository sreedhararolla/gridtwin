"""Seam B property tests for Reallocation: over thousands of seeded random fleets, targets
and partitions, the seq+1 rounds never ask a Device for more than it has left, and a
Device that acts on seq 1 then seq 2 (with response noise) never exceeds its power limit
over the interval and never crosses its Reserve Floor. Plus the staleness boundary."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from gridtwin.fleet.device import apply_command, headroom_mw
from gridtwin.fleet.disaggregate import disaggregate
from gridtwin.fleet.fleet import fleet_state_from_telemetry
from gridtwin.fleet.models import Command, DeviceState, Heartbeat
from gridtwin.fleet.reallocate import (
    needs_reallocation,
    reallocate,
    reallocation_headroom,
    rerate_achievable,
    with_reserve,
)
from gridtwin.planner.models import FleetState
from gridtwin.telemetry.staleness import heartbeat_period_seconds, stale_after_seconds
from tests.test_disaggregate_properties import random_device

CASES = 1500
EPS = 1e-9
ACK_ROUNDING_MW = 5e-7
ROUNDS_RUN: list[int] = []  # Devices sent seq+1 per round, so the test can't pass vacuously
NOW = datetime(2026, 1, 28, 12, 0, tzinfo=UTC)


def command(device_id: str, setpoint_mw: float, seq: int) -> Command:
    return Command(
        idempotency_key=f"run:{NOW.isoformat()}:{device_id}:{seq}",
        run_id="run",
        interval_start=NOW,
        device_id=device_id,
        seq=seq,
        setpoint_mw=setpoint_mw,
        expires_at=NOW + timedelta(minutes=15),
    )


def run_interval(rng: random.Random, devices: list[DeviceState], target_mw: float, rounds: int):
    """Plan, dispatch seq 1 to a partial fleet (some Devices dark, noisy responses), then
    reallocate for up to `rounds` rounds. Returns per-Device (start, end state, total MW)."""
    dark = {d.device_id for d in devices if rng.random() < 0.3}
    state = {d.device_id: d for d in devices}
    total = dict.fromkeys(state, 0.0)
    setpoints = disaggregate(target_mw, devices)
    delivered: dict[str, float] = {}
    for device_id, sp in setpoints.items():
        if device_id in dark:
            continue
        state[device_id], ack = apply_command(
            state[device_id], command(device_id, sp, 1), rng.gauss(1.0, 0.05)
        )
        assert ack.floor_violation is False
        total[device_id] += ack.delivered_mw
        delivered[device_id] = ack.delivered_mw

    achievable = rerate_achievable(target_mw, devices, dark)
    discharge = target_mw >= 0
    for seq in range(2, rounds + 2):
        if not needs_reallocation(achievable, sum(total.values()), 0.05):
            break
        headroom = reallocation_headroom(devices, delivered, discharge)
        extra = reallocate(achievable - sum(total.values()), headroom)
        ROUNDS_RUN.append(len(extra))
        # Never more than the Shortfall, never more than a Device has left, never dark.
        assert abs(sum(extra.values())) <= abs(achievable - sum(total.values())) + EPS
        for device_id, mw in extra.items():
            assert device_id not in dark
            assert abs(mw) <= headroom[device_id] + EPS
            assert (mw >= 0) == discharge
            state[device_id], ack = apply_command(
                state[device_id],
                command(device_id, delivered[device_id] + mw, seq),
                rng.gauss(1.0, 0.05),
                interval_delivered_mw=total[device_id],
            )
            assert ack.floor_violation is False
            total[device_id] += ack.delivered_mw
            delivered[device_id] += ack.delivered_mw
    return {d.device_id: (d, state[d.device_id], total[d.device_id]) for d in devices}


def test_reallocation_never_breaks_floor_or_power_limits():
    rng = random.Random(20260926)
    for _ in range(CASES):
        devices = [random_device(rng, i) for i in range(rng.randint(1, 30))]
        fleet = max(
            sum(headroom_mw(d)[0] for d in devices), sum(headroom_mw(d)[1] for d in devices)
        )
        # Plans below full headroom (a reserve), so there is room to reallocate into.
        target_mw = rng.uniform(-1.0, 1.0) * max(fleet, 1e-3) * rng.uniform(0.3, 1.0)
        for start, end, total_mw in run_interval(rng, devices, target_mw, rounds=3).values():
            # Acks report MW to 6 decimals (1 W), so allow half a watt per round.
            assert abs(total_mw) <= start.max_power_kw / 1000.0 + ACK_ROUNDING_MW * 4
            if total_mw > 0:
                assert end.soc_pct >= start.reserve_floor_pct - EPS
            assert end.soc_pct >= min(start.reserve_floor_pct, start.soc_pct) - EPS
            assert end.soc_pct <= 1.0 + EPS
    assert sum(1 for n in ROUNDS_RUN if n > 0) > CASES // 3


def test_reallocate_splits_by_headroom_and_is_capped():
    assert reallocate(0.3, {"a": 0.1, "b": 0.3}) == pytest.approx({"a": 0.075, "b": 0.225})
    assert reallocate(1.0, {"a": 0.1, "b": 0.3}) == pytest.approx({"a": 0.1, "b": 0.3})
    assert reallocate(-0.2, {"a": 0.1, "b": 0.1}) == pytest.approx({"a": -0.1, "b": -0.1})
    assert reallocate(0.5, {}) == {}
    assert reallocate(0.0, {"a": 0.1}) == {}


def test_needs_reallocation_only_outside_tolerance_and_in_target_direction():
    assert needs_reallocation(1.0, 0.90, 0.05)
    assert not needs_reallocation(1.0, 0.96, 0.05)
    assert not needs_reallocation(1.0, 1.20, 0.05)  # over-delivery is not chased
    assert needs_reallocation(-1.0, -0.90, 0.05)
    assert not needs_reallocation(0.0, 0.0, 0.05)


def test_seq2_setpoint_is_the_new_total_for_the_interval():
    device = DeviceState(
        device_id="d",
        soc_pct=0.9,
        energy_kwh=40.0,
        max_power_kw=10.0,
        round_trip_efficiency=0.9,
        reserve_floor_pct=0.2,
    )
    after1, ack1 = apply_command(device, command("d", 0.006, 1))
    assert ack1.delivered_mw == 0.006
    # Asked for 0.012 in total: the Device adds only what the power limit leaves (0.004).
    _, ack2 = apply_command(after1, command("d", 0.012, 2), interval_delivered_mw=0.006)
    assert abs(ack2.delivered_mw - 0.004) < 1e-9


def test_reserve_holds_back_planner_headroom():
    state = FleetState(discharge_headroom_mw=2.0, charge_headroom_mw=1.0, devices=[])
    planned = with_reserve(state, 0.1)
    assert planned.discharge_headroom_mw == 1.8
    assert planned.charge_headroom_mw == 0.9


def heartbeat(device_id: str, sent_at: datetime) -> Heartbeat:
    return Heartbeat(
        run_id="run",
        state=DeviceState(
            device_id=device_id,
            soc_pct=0.5,
            energy_kwh=39.2,
            max_power_kw=10.0,
            round_trip_efficiency=0.9,
            reserve_floor_pct=0.2,
        ),
        power_mw=0.0,
        healthy=True,
        sent_at=sent_at,
    )


def test_device_is_excluded_within_one_telemetry_period_of_the_stale_threshold():
    """3 missed Heartbeats is the threshold; the flush slack is at most one period, so a
    Device is out of Fleet State no later than one telemetry period after crossing it."""
    speed, missed, flush = 60.0, 3, 1.0
    period = heartbeat_period_seconds(60.0, speed)
    threshold = stale_after_seconds(60.0, speed, missed, flush)
    crossed = missed * period  # the moment the Nth Heartbeat is missed
    assert threshold - crossed <= period

    live = heartbeat("live", NOW - timedelta(seconds=period))
    just_crossed = heartbeat("crossed", NOW - timedelta(seconds=crossed))
    one_period_later = heartbeat("gone", NOW - timedelta(seconds=crossed + period + 0.001))
    state = fleet_state_from_telemetry([live, just_crossed, one_period_later], NOW, threshold)
    assert {d.device_id for d in state.devices} == {"live", "crossed"}
    assert state.stale_devices == 1
