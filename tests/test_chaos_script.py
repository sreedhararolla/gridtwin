"""Seam B (pure domain): the scripted Chaos Scenario format and window selection."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from gridtwin.chaos.script import ScenarioWindow, parse_script, select_window

DAY_START = datetime(2026, 1, 28, 6, tzinfo=UTC)
DAY = [DAY_START + timedelta(minutes=15 * i) for i in range(96)]


def test_worker_kill_script_parses():
    script = parse_script(Path("scenarios/worker-kill.yaml").read_text())
    assert script.name == "worker-kill"
    assert script.window == ScenarioWindow(from_interval=24, intervals=24)
    [step] = script.steps
    assert (step.at_interval, step.apply, step.for_intervals, step.target) == (
        4,
        "worker-kill",
        2,
        None,
    )


def test_demo_full_script_runs_the_video_faults_in_order_one_at_a_time():
    script = parse_script(Path("scenarios/demo-full.yaml").read_text())
    assert script.fixture == "data/fixtures/rtm_spp_lz_houston_2026-01-28.csv"  # no cache needed
    assert [s.apply for s in script.steps] == [
        "worker-kill",
        "partition",
        "duplicate-commands",
        "feed-outage",
    ]
    assert script.steps[0].at_interval == 4  # the 7:00 AM CT peak
    assert script.steps[1].pct == 0.2
    for before, after in zip(script.steps, script.steps[1:], strict=False):
        assert before.at_interval + before.for_intervals < after.at_interval  # no overlap
    last = script.steps[-1]
    assert script.window.intervals is not None
    # The ladder needs clean intervals after the outage to climb back to L0 inside the window.
    assert last.at_interval + last.for_intervals + 2 <= script.window.intervals


def test_defaults_are_the_whole_day_and_no_steps():
    script = parse_script("name: calm")
    assert script.steps == []
    assert select_window(DAY, script.window) == DAY


def test_step_outside_window_is_rejected():
    text = """
name: bad
window: {from_interval: 0, intervals: 4}
steps: [{at_interval: 4, apply: worker-kill}]
"""
    with pytest.raises(ValidationError, match="outside the 4-interval window"):
        parse_script(text)


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValidationError):
        parse_script("name: x\nsteps: [{at_interval: 0, apply: meteor-strike}]")


def test_window_slices_the_day():
    window = select_window(DAY, ScenarioWindow(from_interval=24, intervals=8))
    assert window == DAY[24:32]
    assert window[4] == datetime(2026, 1, 28, 13, tzinfo=UTC)  # the 7:00 AM CT peak


def test_window_past_the_end_of_the_day_is_rejected():
    with pytest.raises(ValueError, match="the day has 96"):
        select_window(DAY, ScenarioWindow(from_interval=90, intervals=8))
