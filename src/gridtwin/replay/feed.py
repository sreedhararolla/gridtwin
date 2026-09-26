"""Pure feed validation: turn a raw Feed Reading into a Market Snapshot, or raise a Feed
Error (Seam B). Checks range, staleness, monotonic timestamps, and outliers against the
recent distribution of valid prices. Runs inside the interval workflow, so no IO here."""

from datetime import datetime
from statistics import median

from pydantic import BaseModel

from gridtwin.replay.models import FeedError, MarketSnapshot

# ERCOT's system-wide offer cap is $5,000/MWh; RT prices can go negative (wind nights), so
# the floor is well below zero rather than at it (docs/DECISIONS.md).
MAX_SANE_PRICE_USD_PER_MWH = 5000.0
MIN_SANE_PRICE_USD_PER_MWH = -500.0


class FeedReading(BaseModel, frozen=True):
    """What the replay feed returned for one Market Interval, before validation."""

    interval_start: datetime  # the interval asked for
    observed_interval_start: datetime | None  # the interval the feed's row is for
    settlement_point: str
    raw_price: float | None


class ValidatorConfig(BaseModel, frozen=True):
    min_price_usd: float = MIN_SANE_PRICE_USD_PER_MWH
    max_price_usd: float = MAX_SANE_PRICE_USD_PER_MWH
    # Robust z-score against the last `window` valid prices: |p - median| / max(MAD, floor).
    # Set wide on purpose: real scarcity spikes (to the $5,000 cap) must pass (DECISIONS.md).
    outlier_z: float = 100.0
    outlier_mad_floor_usd: float = 50.0
    outlier_min_samples: int = 8
    window: int = 16


class FeedHistory(BaseModel, frozen=True):
    """The recent valid prices the validator judges the next reading against."""

    last_interval_start: datetime | None = None
    recent_prices: list[float] = []  # oldest first, at most ValidatorConfig.window

    @property
    def last_price(self) -> float | None:
        return self.recent_prices[-1] if self.recent_prices else None


NO_HISTORY = FeedHistory()
DEFAULT_VALIDATOR = ValidatorConfig()


def validate_snapshot(
    reading: FeedReading,
    history: FeedHistory = NO_HISTORY,
    config: ValidatorConfig = DEFAULT_VALIDATOR,
) -> MarketSnapshot:
    point, when = reading.settlement_point, reading.interval_start.isoformat()
    price = reading.raw_price
    if price is None or reading.observed_interval_start is None:
        raise FeedError(f"no price for {point} at {when}")
    if reading.observed_interval_start < reading.interval_start:
        raise FeedError(
            f"stale: {point} row is for {reading.observed_interval_start.isoformat()}, "
            f"wanted {when}"
        )
    if reading.observed_interval_start != reading.interval_start:
        raise FeedError(f"{point} row is for {reading.observed_interval_start.isoformat()}")
    if history.last_interval_start is not None and (
        reading.interval_start <= history.last_interval_start
    ):
        raise FeedError(
            f"non-monotonic: {when} is not after {history.last_interval_start.isoformat()}"
        )
    if not config.min_price_usd <= price <= config.max_price_usd:
        raise FeedError(f"price ${price:,.2f}/MWh for {point} outside sane bounds")
    z = robust_z(price, history.recent_prices, config)
    if z is not None and z > config.outlier_z:
        raise FeedError(f"price ${price:,.2f}/MWh is an outlier (robust z {z:.0f})")
    return MarketSnapshot(
        interval_start=reading.interval_start,
        settlement_point=point,
        rt_price_usd_per_mwh=price,
    )


def robust_z(price: float, recent: list[float], config: ValidatorConfig) -> float | None:
    """None until there are enough recent valid prices to judge against."""
    if len(recent) < config.outlier_min_samples:
        return None
    mid = median(recent)
    mad = median(abs(p - mid) for p in recent)
    return abs(price - mid) / max(mad, config.outlier_mad_floor_usd)


def remember(
    history: FeedHistory, snapshot: MarketSnapshot, config: ValidatorConfig
) -> FeedHistory:
    return FeedHistory(
        last_interval_start=snapshot.interval_start,
        recent_prices=[*history.recent_prices, snapshot.rt_price_usd_per_mwh][-config.window :],
    )
