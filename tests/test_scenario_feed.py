"""Seam A: feed faults and the Degradation Ladder, in-process. The same scenarios/*.yaml
`make chaos` runs against compose, replayed through the Scenario Runner."""

import pytest

from gridtwin.chaos.runner import load_script
from gridtwin.chaos.script import ChaosScript, ChaosStep
from gridtwin.fleet.models import FleetConfig
from gridtwin.settings import settings
from gridtwin.testing.scenario import ScenarioResult, run_scenario

pytestmark = pytest.mark.asyncio


def fleet_config() -> FleetConfig:
    return settings.fleet_config().model_copy(
        update={"device_count": 200, "shard_count": 4, "seed": 7}
    )


async def run_script(script: ChaosScript, run_id: str) -> ScenarioResult:
    outcome = await run_scenario(
        run_id=run_id,
        fleet=fleet_config(),
        settlement_point=script.settlement_point or settings.settlement_point,
        fixture_path=script.fixture or settings.fixture_path,
        discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        charge_threshold_usd=settings.naive_charge_threshold_usd,
        replay_speed=settings.replay_speed,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
        stale_after_seconds=settings.stale_after_seconds,
        script=script,
        ladder=settings.ladder_config(),
    )
    print(outcome.report.model_dump_json(indent=2, exclude={"degradation_timeline"}))
    for r in outcome.results:
        print(
            f"{r.interval_start:%H:%M} {r.level} feed={r.feed_status:<12} "
            f"price={r.price_usd_per_mwh:8.2f} target={r.target_mw:7.3f} "
            f"delivered={r.delivered_mw:7.3f} commands={r.dispatched_count} {r.feed_detail}"
        )
    for e in outcome.report.degradation_timeline:
        print(f"  {e.interval_start:%H:%M} {e.kind} {e.from_level}->{e.to_level} {e.detail}")
    return outcome


async def test_outlier_is_rejected_and_nothing_is_dispatched_on_it():
    outcome = await run_script(load_script("feed-outlier"), "feed-outlier-inproc")
    [(k, _, _), _] = outcome.chaos_steps
    hit = outcome.results[k]

    # The $9,999 snapshot is rejected: the interval runs on the cached plan (L1) ...
    assert hit.feed_status == "rejected"
    assert "9,999" in hit.feed_detail
    assert hit.level == "L1"
    # ... and nothing acts on it. On $9,999 the naive planner would discharge the whole
    # fleet; the cached plan from a $30 interval idles it, exactly like the interval before.
    assert hit.price_usd_per_mwh != 9999.0
    assert hit.target_mw == outcome.results[k - 1].target_mw == 0.0
    assert hit.delivered_mw == 0.0
    # One bad reading never outlasts the cached plan: L1, then back to L0 after 2 clean.
    assert [r.level for r in outcome.results[k : k + 3]] == ["L1", "L1", "L0"]
    assert outcome.report.worst_level == "L1"
    # The Scenario Report's degradation timeline shows the rejection and the recovery.
    kinds = [(e.kind, e.to_level) for e in outcome.report.degradation_timeline]
    assert kinds == [
        ("snapshot-rejected", "L1"),
        ("level-change", "L1"),
        ("level-change", "L0"),
    ]
    assert outcome.report.degradation_events == 3
    assert outcome.report.reserve_violations == 0


async def test_outage_steps_down_the_ladder_and_recovers_to_l0():
    outcome = await run_script(load_script("feed-outage"), "feed-outage-inproc")
    [(k, _, _), (cleared, _, _)] = outcome.chaos_steps
    results = outcome.results
    levels = [r.level for r in results]
    ladder = settings.ladder_config()

    assert levels[:k] == ["L0"] * k
    # L1 while the last good plan is inside its horizon, then L2 once it runs out.
    assert levels[k : k + ladder.cached_plan_intervals] == ["L1"] * ladder.cached_plan_intervals
    assert levels[k + ladder.cached_plan_intervals : cleared] == ["L2"] * (
        cleared - k - ladder.cached_plan_intervals
    )
    # The breaker opens after K failures: the feed is then not even called (circuit-open)
    # until the cooldown lets a half-open probe through.
    statuses = [r.feed_status for r in results[k:cleared]]
    assert statuses[: ladder.breaker.failure_threshold] == ["outage"] * 3
    assert "circuit-open" in statuses
    # Never a Command without a valid price or a still-valid plan: every degraded interval
    # ran on the cached plan (same target as the last L0 interval) or the Safe Rule, which
    # never charges and only discharges on a last valid price >= the threshold.
    last_l0 = results[k - 1]
    for r in results[k:cleared]:
        if r.level == "L1":
            assert r.target_mw == last_l0.target_mw
        else:
            assert r.level == "L2"
            assert r.price_usd_per_mwh == last_l0.price_usd_per_mwh
            assert r.target_mw == 0.0  # the last valid price, $44, is below the $90 threshold
    # Feed back: the half-open probe succeeds, and N clean intervals later it is L0 again.
    first_ok = next(i for i in range(cleared, len(results)) if results[i].feed_status == "ok")
    back = first_ok + ladder.recover_after_clean - 1
    assert levels[back] == "L0"
    assert all(level != "L0" for level in levels[k:back])
    assert all(level == "L0" for level in levels[back:])
    assert [e.to_level for e in outcome.report.degradation_timeline] == ["L1", "L2", "L0"]
    assert outcome.report.reserve_violations == 0


async def test_outage_with_no_valid_price_yet_holds_at_l3_with_no_commands():
    script = load_script("feed-outage").model_copy(
        update={"steps": [ChaosStep(at_interval=0, apply="feed-outage", for_intervals=3)]}
    )
    outcome = await run_script(script, "feed-outage-l3-inproc")
    held = outcome.results[:3]

    assert [r.level for r in held] == ["L3"] * 3
    assert all(r.target_mw == 0.0 and r.dispatched_count == 0 for r in held)
    assert all(r.delivered_mw == 0.0 for r in held)
    # Commands resume only once a valid price arrives, and the ladder recovers to L0.
    assert outcome.results[-1].level == "L0"
    assert sum(r.dispatched_count for r in outcome.results) > 0
