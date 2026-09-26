"""Seam A: exactly-once effects through the whole dispatch path. A forced activity retry
after a partial send, and the duplicate-commands Chaos Scenario, both deliver Commands more
than once; the Scenario Report must show duplicate effects == 0."""

import pytest

from gridtwin.fleet.models import FleetConfig
from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.settings import settings
from gridtwin.testing.scenario import ScenarioResult, run_scenario

pytestmark = pytest.mark.asyncio

SPIKE_DAY_FIXTURE = "data/fixtures/rtm_spp_lz_houston_2026-01-28.csv"
STALE_AFTER_SECONDS = 30.0


def fleet_config() -> FleetConfig:
    return settings.fleet_config().model_copy(
        update={"device_count": 200, "shard_count": 4, "seed": 7}
    )


async def run_day(run_id: str, **chaos) -> ScenarioResult:
    return await run_scenario(
        run_id=run_id,
        fleet=fleet_config(),
        settlement_point=settings.settlement_point,
        fixture_path=SPIKE_DAY_FIXTURE,
        discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        charge_threshold_usd=settings.naive_charge_threshold_usd,
        replay_speed=settings.replay_speed,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
        stale_after_seconds=STALE_AFTER_SECONDS,
        **chaos,
    )


async def test_retry_after_partial_send_has_no_duplicate_effects():
    clean = await run_day("exactly-once-clean")
    retried = await run_day("exactly-once-retry", partial_send_failures=3)
    report = retried.report
    print(report.model_dump_json(indent=2))

    assert report.retried_dispatches == 3
    assert report.duplicate_deliveries > 0  # the retry re-sent the keys already delivered
    assert report.duplicate_effects == 0
    # One ledger row per Idempotency Key, although the retried batches were upserted twice.
    assert retried.ledger_rows == sum(r.dispatched_count for r in retried.results)
    # Same keys, no second effect: the day plays out exactly as the clean run.
    assert [r.delivered_mw for r in retried.results] == [r.delivered_mw for r in clean.results]
    assert report.reserve_violations == 0


async def test_duplicate_commands_scenario_report():
    fixture_rows = load_fixture_day(settings.settlement_point, SPIKE_DAY_FIXTURE)
    clean = await run_day("duplicates-clean")
    outcome = await run_day("duplicates-on", duplicate_commands=True)
    report = outcome.report
    print(report.model_dump_json(indent=2))

    assert report.intervals == len(fixture_rows)
    assert report.duplicate_deliveries > 0
    assert report.duplicate_effects == 0
    assert report.reserve_violations == 0
    assert report.within_tolerance_pct >= 95.0
    assert [r.delivered_mw for r in outcome.results] == [r.delivered_mw for r in clean.results]
    # The ledger summary covers every interval, every Command acked exactly once.
    assert len(outcome.ledger) == len(fixture_rows)
    assert all(s.acked + s.expired + s.failed + s.unacked == s.issued for s in outcome.ledger)
    assert outcome.ledger_rows == sum(s.issued for s in outcome.ledger)
