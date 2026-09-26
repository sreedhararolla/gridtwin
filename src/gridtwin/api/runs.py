"""Interval Results for a Replay Run: REST for the initial page load, SSE for the live
Live-tab stream (ADR-003: the browser connects straight to FastAPI, not through Next.js)."""

import asyncio
from datetime import date
from typing import Literal

import nats
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gridtwin.dispatch.publish import result_subject
from gridtwin.ledger.models import IntervalResult, LedgerIntervalSummary
from gridtwin.ledger.postgres_repo import PostgresLedgerRepo
from gridtwin.marketdata.prices import DayNotCached
from gridtwin.replay.cli import connect_temporal, start_replay_run
from gridtwin.settings import settings

router = APIRouter()
_repo = PostgresLedgerRepo()


class LatestRun(BaseModel):
    run_id: str | None


class StartRunRequest(BaseModel):
    day: date | None = None  # a cached day (Central-time trading day); None = fixture day
    settlement_point: str | None = None
    strategy: Literal["naive", "lp", "lp_risk"] | None = None  # None = the STRATEGY setting


class StartedRun(BaseModel):
    run_id: str


@router.post("/runs", response_model=StartedRun)
async def start_run(request: StartRunRequest) -> StartedRun:
    """The Live tab's day picker: replay any cached day with the full fleet."""
    try:
        run_id = await start_replay_run(
            await connect_temporal(), request.day, request.settlement_point, request.strategy
        )
    except DayNotCached as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StartedRun(run_id=run_id)


@router.get("/runs/latest", response_model=LatestRun)
async def get_latest_run() -> LatestRun:
    return LatestRun(run_id=await asyncio.to_thread(_repo.latest_run_id))


@router.get("/runs/{run_id}/results", response_model=list[IntervalResult])
async def get_results(run_id: str) -> list[IntervalResult]:
    return await asyncio.to_thread(_repo.list_interval_results, run_id)


@router.get("/runs/{run_id}/ledger", response_model=list[LedgerIntervalSummary])
async def get_ledger(run_id: str) -> list[LedgerIntervalSummary]:
    """The Command Ledger per Market Interval: issued / acked / expired / failed."""
    return await asyncio.to_thread(_repo.ledger_summary, run_id)


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    async def event_source():
        backlog = await asyncio.to_thread(_repo.list_interval_results, run_id)
        for result in backlog:
            yield f"data: {result.model_dump_json()}\n\n"

        nc = await nats.connect(settings.nats_url)
        sub = await nc.subscribe(result_subject(run_id))
        try:
            async for msg in sub.messages:
                yield f"data: {msg.data.decode()}\n\n"
        finally:
            await nc.close()

    return StreamingResponse(event_source(), media_type="text/event-stream")
