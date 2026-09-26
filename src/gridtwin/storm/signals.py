"""Storm mode's signals at a decision time, read from the cache (IO; the decision itself
is pure, storm/reserve.py): the stored Risk Curve made then, and the latest temperature
observed by then. Outage capacity (NP3-233-CD) is not cached, so it is always None
(DECISIONS.md)."""

from datetime import UTC, datetime, timedelta
from functools import lru_cache

import duckdb

from gridtwin.marketdata import cache
from gridtwin.risk.store import risk_curve
from gridtwin.storm.reserve import StormSignals


@lru_cache(maxsize=4)
def _temperatures(root: str, city: str) -> dict[datetime, float]:
    """Hour start (UTC) -> observed °C for `city`, from the weather cache."""
    glob = f"{root}/weather_temperature/**/*.parquet"
    try:
        rows = duckdb.execute(
            f"SELECT interval_start_utc, temperature_c FROM read_parquet('{glob}', "
            "union_by_name=true) WHERE city = ? AND temperature_c IS NOT NULL",
            [city],
        ).fetchall()
    except duckdb.Error:
        return {}  # no weather cached (e.g. CI)
    return {
        (ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)): float(t) for ts, t in rows
    }


def latest_temperature(decision_time: datetime, city: str) -> float | None:
    """The last full hour observed by `decision_time` (an hour is known when it ends)."""
    temps = _temperatures(cache.cache_root().as_posix(), city)
    hour = decision_time.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    return temps.get(hour)


def storm_signals(settlement_point: str, decision_time: datetime, city: str) -> StormSignals:
    curve = risk_curve(settlement_point, decision_time)
    return StormSignals(
        p_spike=curve.p_spike if curve else [],
        outage_mw=None,
        temperature_c=latest_temperature(decision_time, city),
    )
