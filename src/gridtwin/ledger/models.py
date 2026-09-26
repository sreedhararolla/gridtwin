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
    latency_ms: float  # plan -> all shard acks, the interval's dispatch latency
    budget_ms: float = 0.0  # the interval's wall budget: 900 s / replay speed
    online_devices: int = 0  # non-stale Devices in Fleet State at decision time
    shard_count: int = 0
    soc_p10_pct: float = 0.0
    soc_p50_pct: float = 0.0
    soc_p90_pct: float = 0.0
