"""Seam B: fleet construction, shard grouping, Fleet State staleness, the SoC band, the
seeded shard simulator and the telemetry ingester's buffer. No IO."""

from datetime import UTC, datetime, timedelta

from gridtwin.fleet.device import apply_command
from gridtwin.fleet.disaggregate import disaggregate
from gridtwin.fleet.fleet import build_fleet, fleet_state_from_telemetry, group_by_shard, soc_band
from gridtwin.fleet.models import Command, FleetConfig, Heartbeat, ShardReset
from gridtwin.fleet.shard import ShardSimulator
from gridtwin.telemetry.repo import LatestHeartbeats
from gridtwin.telemetry.staleness import stale_after_seconds

NOW = datetime(2026, 1, 28, 18, 0, tzinfo=UTC)
CONFIG = FleetConfig(
    device_count=2000,
    shard_count=20,
    energy_kwh=39.2,
    max_power_kw=10.0,
    round_trip_efficiency=0.9,
    reserve_floor_pct=0.2,
    initial_soc_pct=0.5,
    response_noise_pct=0.02,
    fault_rate=0.01,
    seed=42,
)


def command(device_id: str, setpoint_mw: float) -> Command:
    return Command(
        idempotency_key=f"run:{NOW.isoformat()}:{device_id}:1",
        run_id="run",
        interval_start=NOW,
        device_id=device_id,
        seq=1,
        setpoint_mw=setpoint_mw,
        expires_at=NOW + timedelta(minutes=15),
    )


def test_build_fleet_puts_2000_devices_in_20_shards_of_100():
    fleet = build_fleet(CONFIG)
    assert len(fleet) == 20
    assert all(len(devices) == 100 for devices in fleet.values())
    ids = [d.device_id for devices in fleet.values() for d in devices]
    assert len(set(ids)) == 2000
    assert all(d.shard_id == shard for shard, ds in fleet.items() for d in ds)


def test_group_by_shard_routes_every_setpoint_to_its_devices_shard():
    devices = [d for ds in build_fleet(CONFIG).values() for d in ds]
    batches = group_by_shard(disaggregate(5.0, devices), devices)
    assert len(batches) == 20
    assert sum(len(b) for b in batches.values()) == 2000
    assert set(batches["shard-3"]) == {f"battery-{i}" for i in range(300, 400)}


def heartbeat(device, sent_at: datetime, healthy: bool = True) -> Heartbeat:
    return Heartbeat(run_id="run", state=device, power_mw=0.0, healthy=healthy, sent_at=sent_at)


def test_fleet_state_excludes_stale_and_unhealthy_devices():
    devices = build_fleet(CONFIG)["shard-0"][:3]
    threshold = stale_after_seconds(60.0, 60.0, 3, 1.0)  # 3 missed 1 s heartbeats + flush
    assert threshold == 4.0
    heartbeats = [
        heartbeat(devices[0], NOW - timedelta(seconds=1)),
        heartbeat(devices[1], NOW - timedelta(seconds=10)),  # stale
        heartbeat(devices[2], NOW, healthy=False),
    ]
    state = fleet_state_from_telemetry(heartbeats, NOW, threshold)
    assert [d.device_id for d in state.devices] == [devices[0].device_id]
    assert state.discharge_headroom_mw == 0.01  # one 10 kW device
    assert abs(state.energy_above_floor_mwh - 0.3 * 39.2 / 1000) < 1e-12


def test_soc_band_is_p10_median_p90_in_percent():
    devices = [
        d.model_copy(update={"soc_pct": i / 100})
        for i, d in enumerate(build_fleet(CONFIG)["shard-0"])
    ]
    p10, p50, p90 = soc_band(devices)
    assert (round(p10, 1), round(p50, 1), round(p90, 1)) == (9.9, 49.5, 89.1)


def test_shard_simulator_is_reproducible_for_a_seed_and_applies_noise_and_faults():
    devices = build_fleet(CONFIG)["shard-0"]
    reset = ShardReset(
        run_id="run",
        shard_id="shard-0",
        devices=devices,
        response_noise_pct=0.02,
        fault_rate=0.05,
        seed=42,
    )
    runs = []
    for _ in range(2):
        shard = ShardSimulator()
        shard.reset(reset)
        runs.append(shard.handle_batch([command(d.device_id, 0.005) for d in devices]))
    assert runs[0] == runs[1]
    acks = runs[0]
    delivered = [a.delivered_mw for a in acks if a.applied]
    assert len(delivered) < 100  # some faults at a 5% fault rate
    assert len(set(delivered)) > 10  # noise, not a constant response
    assert all(a.delivered_mw == 0.0 for a in acks if not a.applied)


def test_faulted_device_does_not_act():
    device = build_fleet(CONFIG)["shard-0"][0]
    new_state, ack = apply_command(device, command(device.device_id, 0.01), faulted=True)
    assert ack.applied is False
    assert new_state == device


def test_shard_reset_replaces_devices_and_heartbeats_carry_run_and_shard():
    shard = ShardSimulator()
    devices = build_fleet(CONFIG)["shard-1"]
    shard.reset(
        ShardReset(
            run_id="run-2",
            shard_id="shard-1",
            devices=devices,
            response_noise_pct=0,
            fault_rate=0,
            seed=1,
        )
    )
    beats = shard.heartbeats(NOW)
    assert len(beats) == 100
    assert {hb.run_id for hb in beats} == {"run-2"}
    assert {hb.state.shard_id for hb in beats} == {"shard-1"}


def test_ingester_buffer_keeps_only_the_newest_heartbeat_per_device():
    device = build_fleet(CONFIG)["shard-0"][0]
    buffer = LatestHeartbeats()
    older = heartbeat(device.model_copy(update={"soc_pct": 0.4}), NOW)
    newer = heartbeat(device.model_copy(update={"soc_pct": 0.3}), NOW + timedelta(seconds=1))
    buffer.add([newer])
    buffer.add([older])  # arrives late; must not overwrite
    drained = buffer.drain()
    assert [hb.state.soc_pct for hb in drained] == [0.3]
    assert buffer.drain() == []
