"""Interval Result: the per-interval record the dashboard and Scenario Report read (CONTEXT.md)."""

from datetime import datetime

from pydantic import BaseModel


class IntervalResult(BaseModel, frozen=True):
    run_id: str
    interval_start: datetime
    settlement_point: str
    price_usd_per_mwh: float
    target_mw: float
    achievable_mw: float
    delivered_mw: float
    level: str
    dispatched_count: int
    acked_count: int
    reserve_violations: int
    latency_ms: float
