"""Chaos controller service: applies and clears Chaos Scenarios and writes the chaos event
log. It is the only service with the Docker socket (local demo only, see README).

worker-kill: wait until a Shard dispatch of the run is in flight, SIGKILL the worker
running it, then restart that worker after `duration_s`. The dispatch activity dies with
the worker; Temporal retries it on the surviving worker.

duplicate-commands: tell every simulator (NATS broadcast) to deliver each Command batch
twice and sometimes replay an old one, then switch it off after `duration_s`. Devices
dedupe by Idempotency Key, so duplicate deliveries climb and duplicate effects stay 0.

partition / telemetry-delay: the same broadcast pattern. A seeded share of every Shard's
Devices drops its Commands and Heartbeats, or has its Heartbeats arrive late."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from gridtwin.chaos.docker_engine import DockerEngine, ServiceNotFound
from gridtwin.chaos.events import record_event
from gridtwin.chaos.models import (
    SIMULATOR_SCENARIOS,
    SIMULATORS_TARGET,
    ApplyChaosRequest,
    ChaosEvent,
    ClearChaosRequest,
)
from gridtwin.chaos.temporal_probe import NoDispatchSeen, RunNotRunning, wait_for_dispatch
from gridtwin.ledger.db import init_schema
from gridtwin.replay.cli import connect_temporal
from gridtwin.settings import settings
from gridtwin.transport.nats_transport import NatsTransport

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chaos")

_state: dict = {}
_timers: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(init_schema)
    _state["temporal"] = await connect_temporal()
    _state["docker"] = DockerEngine(settings.docker_socket_path, settings.compose_project)
    _state["nats"] = await NatsTransport.connect(settings.nats_url)
    try:
        yield
    finally:
        await _state["nats"].close()


app = FastAPI(title="GridTwin chaos controller", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


def _later(coro) -> None:
    task = asyncio.create_task(coro)
    _timers.add(task)
    task.add_done_callback(_timers.discard)


async def _record(event: ChaosEvent) -> ChaosEvent:
    await asyncio.to_thread(record_event, event)
    log.info(
        "chaos %s %s run=%s target=%s", event.action, event.scenario, event.run_id, event.target
    )
    return event


async def _restart(run_id: str, worker: str, detail: str) -> ChaosEvent:
    await _state["docker"].start(worker)
    return await _record(
        ChaosEvent(
            run_id=run_id,
            at=datetime.now(UTC),
            scenario="worker-kill",
            action="clear",
            target=worker,
            detail=detail,
        )
    )


async def _restart_later(run_id: str, worker: str, delay_s: float) -> None:
    await asyncio.sleep(delay_s)
    if not await _state["docker"].is_running(worker):
        await _restart(run_id, worker, f"restarted after {delay_s:.0f} s")


async def _broadcast(request: ApplyChaosRequest, active: bool) -> str:
    """Switch a simulator-side scenario on or off on every simulator; returns the detail
    line for the event log."""
    nats = _state["nats"]
    if request.scenario == "duplicate-commands":
        await nats.set_duplicates(active)
        return "every batch delivered twice, old batches replayed"
    if request.scenario == "partition":
        pct = request.pct if request.pct is not None else settings.chaos_partition_pct
        await nats.set_partition(pct if active else 0.0)
        return f"{pct * 100:.0f} % of devices dark: Commands and Heartbeats dropped"
    pct = request.pct if request.pct is not None else settings.chaos_telemetry_delay_pct
    delay_s = request.delay_s or settings.chaos_telemetry_delay_seconds
    await nats.set_telemetry_delay(delay_s if active else 0.0, pct)
    return f"Heartbeats of {pct * 100:.0f} % of devices {delay_s:.0f} s late"


async def _set_simulator_chaos(request: ApplyChaosRequest, active: bool, why: str) -> ChaosEvent:
    detail = await _broadcast(request, active)
    return await _record(
        ChaosEvent(
            run_id=request.run_id,
            at=datetime.now(UTC),
            scenario=request.scenario,
            action="apply" if active else "clear",
            target=SIMULATORS_TARGET,
            detail=detail if active else why,
        )
    )


async def _clear_simulator_chaos_later(request: ApplyChaosRequest, delay_s: float) -> None:
    await asyncio.sleep(delay_s)
    active: dict[str, ApplyChaosRequest] = _state.setdefault("simulator_chaos", {})
    if active.get(request.scenario) is request:
        del active[request.scenario]
        await _set_simulator_chaos(request, False, f"cleared after {delay_s:.0f} s")


@app.post("/clear", response_model=ChaosEvent)
async def clear(request: ClearChaosRequest) -> ChaosEvent:
    if request.scenario in SIMULATOR_SCENARIOS:
        active: dict[str, ApplyChaosRequest] = _state.setdefault("simulator_chaos", {})
        applied = active.pop(request.scenario, None) or ApplyChaosRequest(
            scenario=request.scenario, run_id=request.run_id
        )
        return await _set_simulator_chaos(applied, False, "cleared on request")
    try:
        return await _restart(request.run_id, request.target, "restarted on request")
    except ServiceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/apply", response_model=ChaosEvent)
async def apply(request: ApplyChaosRequest) -> ChaosEvent:
    delay_s = request.duration_s or settings.chaos_restart_delay_seconds
    if request.scenario in SIMULATOR_SCENARIOS:
        _state.setdefault("simulator_chaos", {})[request.scenario] = request
        event = await _set_simulator_chaos(request, True, "")
        _later(_clear_simulator_chaos_later(request, delay_s))
        return event

    try:
        dispatch = await wait_for_dispatch(
            _state["temporal"],
            request.run_id,
            request.target,
            settings.chaos_dispatch_wait_seconds,
        )
        killed_at = datetime.now(UTC)
        await _state["docker"].kill(dispatch.worker)
    except (RunNotRunning, NoDispatchSeen) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ServiceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    event = await _record(
        ChaosEvent(
            run_id=request.run_id,
            at=killed_at,
            scenario=request.scenario,
            action="apply",
            target=dispatch.worker,
            interval_start=dispatch.interval_start,
            detail=f"killed mid-dispatch ({dispatch.activity_id})",
        )
    )
    _later(_restart_later(request.run_id, dispatch.worker, delay_s))
    return event
