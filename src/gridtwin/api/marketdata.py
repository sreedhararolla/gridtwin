"""Data tab: cached days for the picker, and an RT-vs-DAM price series for one day.

Timestamps are always UTC on the wire (spec: "Store all timestamps in UTC;
display in Central time"); the web layer converts for display.
"""

import asyncio
from datetime import date, datetime

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel

from gridtwin.marketdata import cache
from gridtwin.settings import settings

router = APIRouter(prefix="/marketdata")


class CachedDay(BaseModel):
    day: date
    max_rt_price_usd_per_mwh: float


class PricePoint(BaseModel):
    interval_start: datetime
    rt_price_usd_per_mwh: float | None
    dam_price_usd_per_mwh: float | None


def _utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True)


def _cached_days(settlement_point: str) -> list[CachedDay]:
    days = sorted(cache.cached_days("rt_spp", "ALL"))
    result = []
    for day in days:
        df = cache.read_day("rt_spp", "ALL", day)
        df = df[df["settlement_point"] == settlement_point]
        if df.empty:
            continue
        result.append(
            CachedDay(day=day, max_rt_price_usd_per_mwh=float(df["price_usd_per_mwh"].max()))
        )
    return result


def _prices_for_day(settlement_point: str, day: date) -> list[PricePoint]:
    if not cache.has_day("rt_spp", "ALL", day):
        return []
    rt = cache.read_day("rt_spp", "ALL", day)
    rt = rt[rt["settlement_point"] == settlement_point].copy()
    rt["interval_start_utc"] = _utc(rt["interval_start_utc"])
    rt = rt.sort_values("interval_start_utc")

    dam_by_interval: dict[datetime, float] = {}
    if cache.has_day("dam_spp", "ALL", day):
        dam = cache.read_day("dam_spp", "ALL", day)
        dam = dam[dam["settlement_point"] == settlement_point].copy()
        dam["interval_start_utc"] = _utc(dam["interval_start_utc"])
        dam_by_interval = dict(
            zip(dam["interval_start_utc"], dam["price_usd_per_mwh"], strict=True)
        )

    return [
        PricePoint(
            interval_start=row.interval_start_utc.to_pydatetime(),
            rt_price_usd_per_mwh=float(row.price_usd_per_mwh),
            dam_price_usd_per_mwh=dam_by_interval.get(row.interval_start_utc),
        )
        for row in rt.itertuples()
    ]


@router.get("/days", response_model=list[CachedDay])
async def get_cached_days(settlement_point: str = settings.settlement_point) -> list[CachedDay]:
    return await asyncio.to_thread(_cached_days, settlement_point)


@router.get("/prices", response_model=list[PricePoint])
async def get_prices(
    day: date, settlement_point: str = settings.settlement_point
) -> list[PricePoint]:
    return await asyncio.to_thread(_prices_for_day, settlement_point, day)
