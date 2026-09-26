"""Seam A, compose mode: the scripted worker-kill Chaos Scenario against the full stack
(`make up` first; run by `make test-e2e`). A worker is SIGKILLed mid-dispatch at the spike
peak; the run must miss no interval and meet its SLOs, and Temporal history must show the
killed dispatch retried to completion on the other worker."""

import pytest

from gridtwin.chaos.runner import load_script, run_chaos_script
from gridtwin.settings import settings

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def test_worker_kill_meets_slos():
    script = load_script("worker-kill")
    outcome = await run_chaos_script(script)
    report = outcome.report
    print(report.model_dump_json(indent=2))
    for row in outcome.slo:
        print(f"{row.name}: target {row.target}, actual {row.actual}, ok={row.ok}")

    assert report.intervals == script.window.intervals
    assert report.missed_intervals == 0
    assert report.reserve_violations == 0
    assert report.within_tolerance_pct >= 95.0
    assert 0.0 < report.max_recovery_s <= settings.chaos_recovery_slo_seconds

    [kill] = [e for e in outcome.events if e.action == "apply"]
    assert kill.scenario == "worker-kill"
    assert kill.target in {"worker-a", "worker-b"}
    assert kill.interval_start is not None

    # The killed dispatch shows up in Temporal history as attempt 2, run to completion
    # by the surviving worker.
    assert outcome.retries
    assert all(a.completed and a.worker != kill.target for a in outcome.retries)
    assert outcome.slos_met
