"""Risk Curves for the Live tab, and the risk model report `make train` wrote."""

import asyncio
from datetime import date

from fastapi import APIRouter, HTTPException

from gridtwin.risk.models import RiskDay, RiskReport
from gridtwin.risk.paths import report_path
from gridtwin.risk.store import risk_day
from gridtwin.settings import settings

router = APIRouter(prefix="/risk")


@router.get("/day", response_model=RiskDay)
async def get_risk_day(day: date, settlement_point: str = settings.settlement_point) -> RiskDay:
    result = await asyncio.to_thread(risk_day, settlement_point, day)
    if result is None:
        raise HTTPException(status_code=404, detail="no Risk Curve for that day; run `make train`")
    return result


def _load_report() -> RiskReport | None:
    path = report_path()
    return RiskReport.model_validate_json(path.read_text()) if path.exists() else None


@router.get("/report", response_model=RiskReport)
async def get_risk_report() -> RiskReport:
    report = await asyncio.to_thread(_load_report)
    if report is None:
        raise HTTPException(status_code=404, detail="no risk model yet; run `make train`")
    return report
