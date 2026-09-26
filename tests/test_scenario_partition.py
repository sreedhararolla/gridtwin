"""Seam A: Device partition and telemetry delay, in-process. The same scenarios/*.yaml
`make chaos` runs against compose, replayed through the Scenario Runner."""

import pytest

from gridtwin.chaos.runner import load_script
from gridtwin.fleet.models import FleetConfig
from gridtwin.settings import settings
from gridtwin.testing.scenario import ScenarioResult, run_scenario

pytestmark = pytest.mark.asyncio

DEVICES = 200


def fleet_config() -> FleetConfig:
    return settings.fleet_config().model_copy(
        update={"device_count": DEVICES, "shard_count": 4, "seed": 7}
    )


async def run_script(name: str, run_id: str) -> ScenarioResult:
    script = load_script(name)
    return await run_scenario(
        run_id=run_id,
        fleet=fleet_config(),
        settlement_point=script.settlement_point or settings.settlement_point,
        fixture_path=script.fixture or settings.fixture_path,
        discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        charge_threshold_usd=settings.naive_charge_threshold_usd,
        replay_speed=settings.replay_speed,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
        # The real threshold: 3 missed 1 s Heartbeats + the 1 s flush at 60x.
        stale_after_seconds=settings.stale_after_seconds,
        script=script,
    )


async def test_partition_20pct_stays_within_tolerance_of_achievable():
    outcome = await run_script("partition", "partition-inproc")
    report = outcome.report
    print(report.model_dump_json(indent=2))
    for r in outcome.results:
        print(
            f"{r.interval_start:%H:%M} online={r.online_devices} stale={r.stale_devices} "
            f"unresponsive={r.unresponsive_devices} target={r.target_mw:.3f} "
            f"planned={r.planned_achievable_mw:.3f} achievable={r.achievable_mw:.3f} "
            f"delivered={r.delivered_mw:.3f} rounds={r.reallocation_rounds} "
            f"moved={r.reallocated_mw:.3f}"
        )

    dark = round(0.2 * DEVICES)
    [(applied_at, _, _), (cleared_at, _, _)] = outcome.chaos_steps
    hit = outcome.results[applied_at]
    after = outcome.results[applied_at + 1]

    assert report.intervals == 12
    assert report.within_tolerance_pct >= 95.0
    assert report.reserve_violations == 0
    # The partition lands after the interval's telemetry: those Devices get Commands they
    # never answer, and the Achievable Target is re-rated without them.
    assert hit.unresponsive_devices == dark
    assert abs(hit.achievable_mw) < abs(hit.planned_achievable_mw)
    # Their Shortfall moves to reachable Devices with Headroom, in bounded seq+1 rounds.
    assert hit.reallocated_mw > 0
    assert hit.reallocated_devices > 0
    assert 1 <= hit.reallocation_rounds <= settings.reallocation_max_rounds
    assert all(r.reallocation_rounds <= settings.reallocation_max_rounds for r in outcome.results)
    # One telemetry period later they are stale and out of Fleet State.
    assert after.stale_devices == dark
    assert after.online_devices == DEVICES - dark
    assert after.unresponsive_devices == 0
    # Cleared: they heartbeat again and rejoin the next interval.
    assert outcome.results[cleared_at + 1].online_devices == DEVICES
    assert report.duplicate_effects == 0
