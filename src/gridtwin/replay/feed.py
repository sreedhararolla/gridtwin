"""Pure feed validation: turn a raw price into a Market Snapshot, or raise a Feed Error.

Ticket 08 adds the full circuit breaker and degradation ladder (L1 cached plan, L2 safe
rule, staged recovery). Ticket 02 wires the seam with a single sanity check so a missing
or out-of-range price fails loudly instead of silently dispatching on garbage data.
"""

from datetime import datetime

from gridtwin.replay.models import FeedError, MarketSnapshot

MAX_SANE_PRICE_USD_PER_MWH = 5000.0


def validate_snapshot(
    interval_start: datetime, settlement_point: str, raw_price: float | None
) -> MarketSnapshot:
    if raw_price is None:
        raise FeedError(f"no price for {settlement_point} at {interval_start.isoformat()}")
    if raw_price < 0 or raw_price > MAX_SANE_PRICE_USD_PER_MWH:
        raise FeedError(f"price {raw_price} for {settlement_point} outside sane bounds")
    return MarketSnapshot(
        interval_start=interval_start,
        settlement_point=settlement_point,
        rt_price_usd_per_mwh=raw_price,
    )
