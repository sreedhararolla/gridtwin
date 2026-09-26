"""The Scenario Runner in compose mode: replays a scripted Chaos Scenario against the
running stack and returns a Scenario Report plus the SLO table (Seam A, compose).

It starts the Replay Run on Temporal, applies each step through the API when the run
reaches the step's interval, waits for the run to finish, then reads results, chaos
events and Temporal history. The same script, seed and window give the same run."""

import asyncio
import time
import uuid
from pathlib import Path

import httpx
from pydantic import BaseModel

from gridtwin.chaos.history import ActivityAttempt, dispatch_attempts
from gridtwin.chaos.models import ChaosEvent, SloReport, SloRow
from gridtwin.chaos.script import ChaosScript, parse_script, select_window
from gridtwin.chaos.slo import max_recovery_s, slo_rows
from gridtwin.dispatch.workflows import (
    INTERVAL_SECONDS,
    WORKFLOW_TASK_TIMEOUT,
    ReplayRunWorkflow,
)
from gridtwin.ledger.models import IntervalResult
from gridtwin.marketdata.prices import load_day_prices
from gridtwin.replay.cli import build_run_input, connect_temporal
from gridtwin.settings import settings
from gridtwin.testing.scenario import ScenarioReport, build_report

POLL_SECONDS = 0.5
CLEAR_GRACE_SECONDS = 5.0


class ChaosRunOutcome(BaseModel):
    run_id: str
    report: ScenarioReport
    slo: list[SloRow]
    events: list[ChaosEvent]
    retries: list[ActivityAttempt]  # dispatch attempts > 1 in the intervals faults hit

    @property
    def slos_met(self) -> bool:
        return all(row.ok for row in self.slo)


def load_script(name: str) -> ChaosScript:
    return parse_script((Path(settings.scenarios_dir) / f"{name}.yaml").read_text())


async def _wait_for_results(api: httpx.AsyncClient, run_id: str, count: int) -> None:
    while True:
        res = await api.get(f"/runs/{run_id}/results")
        res.raise_for_status()
        if len(res.json()) >= count:
            return
        await asyncio.sleep(POLL_SECONDS)


async def run_chaos_script(script: ChaosScript) -> ChaosRunOutcome:
    point = script.settlement_point or settings.settlement_point
    fixture_path = script.fixture or settings.fixture_path
    rows = load_day_prices(point, script.day, fixture_path)
    window = select_window([interval_start for interval_start, _ in rows], script.window)
    run_id = f"chaos-{script.name}-{uuid.uuid4().hex[:6]}"
    wall_s_per_interval = INTERVAL_SECONDS / settings.replay_speed

    run_input = build_run_input(run_id, script.day, point).model_copy(
        update={"fixture_path": fixture_path, "interval_starts": window}
    )
    client = await connect_temporal()
    handle = await client.start_workflow(
        ReplayRunWorkflow.run,
        run_input,
        id=f"replay:{run_id}",
        task_queue=settings.task_queue,
        task_timeout=WORKFLOW_TASK_TIMEOUT,
    )

    timeout = settings.chaos_dispatch_wait_seconds + 10.0
    async with httpx.AsyncClient(base_url=settings.api_url, timeout=timeout) as api:
        for step in sorted(script.steps, key=lambda s: s.at_interval):
            # `at_interval` results recorded => the next dispatch in flight is interval k.
            await _wait_for_results(api, run_id, step.at_interval)
            if step.at_offset_s:
                await asyncio.sleep(step.at_offset_s)
            res = await api.post(
                "/chaos/apply",
                json={
                    "scenario": step.apply,
                    "run_id": run_id,
                    "target": step.target,
                    "duration_s": step.for_intervals * wall_s_per_interval,
                    "pct": step.pct,
                    "delay_s": step.delay_s,
                },
            )
            res.raise_for_status()

        await handle.result()
        results = [IntervalResult.model_validate(r) for r in (await _get(api, run_id, "results"))]
        # Let the controller clear faults that outlast the window, so the stack is whole.
        deadline = (
            time.monotonic()
            + CLEAR_GRACE_SECONDS
            + max((s.for_intervals * wall_s_per_interval for s in script.steps), default=0.0)
        )
        events = await _events(api, run_id)
        while time.monotonic() < deadline and _uncleared(events):
            await asyncio.sleep(POLL_SECONDS)
            events = await _events(api, run_id)
        slo_report = SloReport.model_validate(await _get(api, run_id, "slo"))

    retries: list[ActivityAttempt] = []
    for recovery in slo_report.recoveries:
        attempts = await dispatch_attempts(client, run_id, recovery.interval_start)
        retries.extend(a for a in attempts if a.attempt > 1)

    worst_recovery = max_recovery_s(slo_report.recoveries)
    report = build_report(results, settings.tolerance_pct).model_copy(
        update={
            "missed_intervals": max(len(window) - len(results), 0),
            "chaos_events": sum(1 for e in events if e.action == "apply"),
            # -1 = a faulted interval never completed (the SLO table says so too).
            "max_recovery_s": -1.0 if worst_recovery is None else worst_recovery,
            "retried_dispatches": len(retries),
        }
    )
    slo = slo_rows(
        results,
        slo_report.recoveries,
        settings.tolerance_pct,
        settings.chaos_recovery_slo_seconds,
        expected_intervals=len(window),
    )
    return ChaosRunOutcome(run_id=run_id, report=report, slo=slo, events=events, retries=retries)


async def _get(api: httpx.AsyncClient, run_id: str, path: str):
    res = await api.get(f"/runs/{run_id}/{path}")
    res.raise_for_status()
    return res.json()


async def _events(api: httpx.AsyncClient, run_id: str) -> list[ChaosEvent]:
    return [ChaosEvent.model_validate(e) for e in await _get(api, run_id, "chaos-events")]


def _uncleared(events: list[ChaosEvent]) -> bool:
    applied = sum(1 for e in events if e.action == "apply")
    cleared = sum(1 for e in events if e.action == "clear")
    return cleared < applied
