"""Seam A, compose mode: the scripted duplicate-commands Chaos Scenario against the full
stack (`make up` first; run by `make test-e2e`). The simulators deliver every batch twice
and replay old ones; Devices dedupe by Idempotency Key, so duplicate effects stay 0."""

import pytest

from gridtwin.chaos.runner import load_script, run_chaos_script

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def test_duplicate_commands_have_no_duplicate_effects():
    script = load_script("duplicates")
    outcome = await run_chaos_script(script)
    report = outcome.report
    print(report.model_dump_json(indent=2))

    assert report.intervals == script.window.intervals
    assert report.missed_intervals == 0
    assert report.duplicate_deliveries > 0
    assert report.duplicate_effects == 0
    assert report.reserve_violations == 0

    applied = [e for e in outcome.events if e.action == "apply"]
    assert [e.scenario for e in applied] == ["duplicate-commands"]
    assert any(e.action == "clear" for e in outcome.events)
    assert outcome.slos_met
