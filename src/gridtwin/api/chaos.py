"""Chaos controls and evidence for the Live tab. Apply/clear are forwarded to the chaos
controller (the only service holding the Docker socket); the event log and the SLO table
are read straight from Postgres."""

import asyncio

import httpx
from fastapi import APIRouter, HTTPException

from gridtwin.chaos.events import interval_completed_at, list_events
from gridtwin.chaos.models import ApplyChaosRequest, ChaosEvent, ClearChaosRequest, SloReport
from gridtwin.chaos.slo import recovery_times, slo_rows
from gridtwin.ledger.postgres_repo import PostgresLedgerRepo
from gridtwin.settings import settings

router = APIRouter()
_repo = PostgresLedgerRepo()


async def _forward(path: str, body: dict) -> ChaosEvent:
    timeout = settings.chaos_dispatch_wait_seconds + 10.0
    try:
        async with httpx.AsyncClient(base_url=settings.chaos_controller_url) as client:
            res = await client.post(path, json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"chaos controller: {exc}") from exc
    if res.status_code >= 400:
        raise HTTPException(status_code=res.status_code, detail=res.json().get("detail"))
    return ChaosEvent.model_validate(res.json())


@router.post("/chaos/apply", response_model=ChaosEvent)
async def apply_chaos(request: ApplyChaosRequest) -> ChaosEvent:
    return await _forward("/apply", request.model_dump())


@router.post("/chaos/clear", response_model=ChaosEvent)
async def clear_chaos(request: ClearChaosRequest) -> ChaosEvent:
    return await _forward("/clear", request.model_dump())


@router.get("/runs/{run_id}/chaos-events", response_model=list[ChaosEvent])
async def get_chaos_events(run_id: str) -> list[ChaosEvent]:
    return await asyncio.to_thread(list_events, run_id)


def build_slo_report(run_id: str) -> SloReport:
    results = _repo.list_interval_results(run_id)
    recoveries = recovery_times(list_events(run_id), interval_completed_at(run_id))
    return SloReport(
        run_id=run_id,
        rows=slo_rows(
            results,
            recoveries,
            settings.tolerance_pct,
            settings.chaos_recovery_slo_seconds,
        ),
        recoveries=recoveries,
    )


@router.get("/runs/{run_id}/slo", response_model=SloReport)
async def get_slo(run_id: str) -> SloReport:
    return await asyncio.to_thread(build_slo_report, run_id)
