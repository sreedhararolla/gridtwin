"""Chaos controller service: applies and clears Chaos Scenarios and writes the chaos event
log. It is the only service with the Docker socket (local demo only, see README).

worker-kill: wait until a Shard dispatch of the run is in flight, SIGKILL the worker
running it, then restart that worker after `duration_s`. The dispatch activity dies with
the worker; Temporal retries it on the surviving worker.

duplicate-commands: tell every simulator (NATS broadcast) to deliver each Command batch
twice and sometimes replay an old one, then switch it off after `duration_s`. Devices
dedupe by Idempotency Key, so duplicate deliveries climb and duplicate effects stay 0."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from gridtwin.chaos.docker_engine import DockerEngine, ServiceNotFound
from gridtwin.chaos.events import record_event
from gridtwin.chaos.models import (
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


async def _set_duplicates(run_id: str, active: bool, detail: str) -> ChaosEvent:
    await _state["nats"].set_duplicates(active)
    return await _record(
        ChaosEvent(
            run_id=run_id,
            at=datetime.now(UTC),
            scenario="duplicate-commands",
            action="apply" if active else "clear",
            target=SIMULATORS_TARGET,
            detail=detail,
        )
    )


async def _clear_duplicates_later(run_id: str, delay_s: float) -> None:
    await asyncio.sleep(delay_s)
    if _state.get("duplicates_run") == run_id:
        _state.pop("duplicates_run", None)
        await _set_duplicates(run_id, False, f"cleared after {delay_s:.0f} s")


@app.post("/clear", response_model=ChaosEvent)
async def clear(request: ClearChaosRequest) -> ChaosEvent:
    if request.scenario == "duplicate-commands":
        _state.pop("duplicates_run", None)
        return await _set_duplicates(request.run_id, False, "cleared on request")
    try:
        return await _restart(request.run_id, request.target, "restarted on request")
    except ServiceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/apply", response_model=ChaosEvent)
async def apply(request: ApplyChaosRequest) -> ChaosEvent:
    delay_s = request.duration_s or settings.chaos_restart_delay_seconds
    if request.scenario == "duplicate-commands":
        _state["duplicates_run"] = request.run_id
        event = await _set_duplicates(
            request.run_id, True, "every batch delivered twice, old batches replayed"
        )
        _later(_clear_duplicates_later(request.run_id, delay_s))
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
