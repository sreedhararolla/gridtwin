"""The Market Snapshot: the pure domain's validated view of one interval's inputs."""

from datetime import datetime

from pydantic import BaseModel


class MarketSnapshot(BaseModel, frozen=True):
    interval_start: datetime
    settlement_point: str
    rt_price_usd_per_mwh: float


class FeedError(Exception):
    """A Market Snapshot that is missing, stale or fails validation."""
