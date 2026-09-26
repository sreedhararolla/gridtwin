"""Chaos controller service: applies and clears Chaos Scenarios and writes the chaos event
log. It is the only service with the Docker socket (local demo only, see README).

worker-kill: wait until a Shard dispatch of the run is in flight, SIGKILL the worker
running it, then restart that worker after `duration_s`. The dispatch activity dies with
the worker; Temporal retries it on the surviving worker."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from gridtwin.chaos.docker_engine import DockerEngine, ServiceNotFound
from gridtwin.chaos.events import record_event
from gridtwin.chaos.models import ApplyChaosRequest, ChaosEvent, ClearChaosRequest
from gridtwin.chaos.temporal_probe import NoDispatchSeen, RunNotRunning, wait_for_dispatch
from gridtwin.ledger.db import init_schema
from gridtwin.replay.cli import connect_temporal
from gridtwin.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chaos")

_state: dict = {}
_restarts: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(init_schema)
    _state["temporal"] = await connect_temporal()
    _state["docker"] = DockerEngine(settings.docker_socket_path, settings.compose_project)
    yield


app = FastAPI(title="GridTwin chaos controller", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


async def _restart(run_id: str, worker: str, detail: str) -> ChaosEvent:
    await _state["docker"].start(worker)
    event = ChaosEvent(
        run_id=run_id,
        at=datetime.now(UTC),
        scenario="worker-kill",
        action="clear",
        target=worker,
        detail=detail,
    )
    await asyncio.to_thread(record_event, event)
    log.info("chaos clear worker-kill run=%s target=%s", run_id, worker)
    return event


async def _restart_later(run_id: str, worker: str, delay_s: float) -> None:
    await asyncio.sleep(delay_s)
    if not await _state["docker"].is_running(worker):
        await _restart(run_id, worker, f"restarted after {delay_s:.0f} s")


@app.post("/clear", response_model=ChaosEvent)
async def clear(request: ClearChaosRequest) -> ChaosEvent:
    try:
        return await _restart(request.run_id, request.target, "restarted on request")
    except ServiceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/apply", response_model=ChaosEvent)
async def apply(request: ApplyChaosRequest) -> ChaosEvent:
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

    event = ChaosEvent(
        run_id=request.run_id,
        at=killed_at,
        scenario=request.scenario,
        action="apply",
        target=dispatch.worker,
        interval_start=dispatch.interval_start,
        detail=f"killed mid-dispatch ({dispatch.activity_id})",
    )
    await asyncio.to_thread(record_event, event)
    log.info(
        "chaos apply worker-kill run=%s target=%s interval_start=%s",
        request.run_id,
        dispatch.worker,
        dispatch.interval_start.isoformat(),
    )

    delay_s = request.duration_s or settings.chaos_restart_delay_seconds
    task = asyncio.create_task(_restart_later(request.run_id, dispatch.worker, delay_s))
    _restarts.add(task)
    task.add_done_callback(_restarts.discard)
    return event
