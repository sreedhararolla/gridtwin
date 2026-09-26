"""Seam A, compose mode: the scripted partition and telemetry-delay Chaos Scenarios
against the full stack (`make up` first; run by `make test-e2e`)."""

import pytest

from gridtwin.chaos.runner import load_script, run_chaos_script
from gridtwin.settings import settings

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


def print_outcome(outcome) -> None:
    print(outcome.report.model_dump_json(indent=2))
    for row in outcome.slo:
        print(f"{row.name}: target {row.target}, actual {row.actual}, ok={row.ok}")
    for e in outcome.events:
        print(f"{e.at.isoformat()} {e.scenario} {e.action} {e.target} {e.detail}")


async def test_partition_20pct_tracks_achievable_target():
    script = load_script("partition")
    outcome = await run_chaos_script(script)
    print_outcome(outcome)
    report = outcome.report
    dark = round(settings.chaos_partition_pct * settings.device_count)

    assert report.intervals == script.window.intervals
    assert report.missed_intervals == 0
    assert report.within_tolerance_pct >= 95.0
    assert report.reserve_violations == 0
    # The partitioned Devices went stale and left Fleet State.
    assert report.max_stale_devices == dark
    assert report.min_online_devices == settings.device_count - dark
    applied = [e for e in outcome.events if e.action == "apply"]
    assert [e.scenario for e in applied] == ["partition"]
    assert any(e.action == "clear" and e.scenario == "partition" for e in outcome.events)
    assert outcome.slos_met


async def test_telemetry_delay_has_no_reserve_violations():
    script = load_script("telemetry-delay")
    outcome = await run_chaos_script(script)
    print_outcome(outcome)
    report = outcome.report
    delayed = round(settings.chaos_telemetry_delay_pct * settings.device_count)

    assert report.intervals == script.window.intervals
    assert report.missed_intervals == 0
    assert report.reserve_violations == 0
    assert report.within_tolerance_pct >= 95.0
    # Late telemetry made those Devices stale: the Achievable Target was de-rated.
    assert report.max_stale_devices == delayed
    assert report.min_online_devices == settings.device_count - delayed
    assert outcome.slos_met
