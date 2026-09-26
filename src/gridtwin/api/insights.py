"""Insights tab: what `make backtest` and `make insights` wrote from the cache."""

import asyncio

from fastapi import APIRouter, HTTPException

from gridtwin.insights import report
from gridtwin.insights.backtest import load_report
from gridtwin.insights.report import InsightsReport
from gridtwin.planner.backtest import BacktestReport

router = APIRouter(prefix="/insights")


@router.get("/backtest", response_model=BacktestReport)
async def get_backtest() -> BacktestReport:
    result = await asyncio.to_thread(load_report)
    if result is None:
        raise HTTPException(status_code=404, detail="no backtest yet; run `make backtest`")
    return result


@router.get("/report", response_model=InsightsReport)
async def get_insights() -> InsightsReport:
    result = await asyncio.to_thread(report.load_report)
    if result is None:
        raise HTTPException(status_code=404, detail="no insights yet; run `make insights`")
    return result
