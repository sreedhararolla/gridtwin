"""Interval Results for a Replay Run: REST for the initial page load, SSE for the live
Live-tab stream (ADR-003: the browser connects straight to FastAPI, not through Next.js)."""

import asyncio

import nats
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gridtwin.dispatch.publish import result_subject
from gridtwin.ledger.models import IntervalResult
from gridtwin.ledger.postgres_repo import PostgresLedgerRepo
from gridtwin.settings import settings

router = APIRouter()
_repo = PostgresLedgerRepo()


class LatestRun(BaseModel):
    run_id: str | None


@router.get("/runs/latest", response_model=LatestRun)
async def get_latest_run() -> LatestRun:
    return LatestRun(run_id=await asyncio.to_thread(_repo.latest_run_id))


@router.get("/runs/{run_id}/results", response_model=list[IntervalResult])
async def get_results(run_id: str) -> list[IntervalResult]:
    return await asyncio.to_thread(_repo.list_interval_results, run_id)


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
