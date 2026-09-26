"""Insights tab: the strategy backtest that `make backtest` wrote from the cache."""

import asyncio

from fastapi import APIRouter, HTTPException

from gridtwin.insights.backtest import load_report
from gridtwin.planner.backtest import BacktestReport

router = APIRouter(prefix="/insights")


@router.get("/backtest", response_model=BacktestReport)
async def get_backtest() -> BacktestReport:
    report = await asyncio.to_thread(load_report)
    if report is None:
        raise HTTPException(status_code=404, detail="no backtest yet; run `make backtest`")
    return report
