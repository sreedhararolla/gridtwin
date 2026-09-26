"""Keyless ERCOT historical data via the `gridstatus` OSS library.

`gridstatus.Ercot` scrapes ERCOT's public MIS report archives directly, no
API key needed. See docs/DECISIONS.md for a build-environment note: from
this sandbox ercot.com returns 403 for every path, keyless or keyed, so
these calls fail here; `ingest.py` treats a failed fetch as a per-day gap
rather than crashing the run.
"""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import gridstatus
import pandas as pd

from gridtwin.marketdata.throttle import RateLimiter

SETTLEMENT_POINTS = ["LZ_HOUSTON", "LZ_NORTH", "LZ_SOUTH", "HB_HOUSTON", "HB_NORTH", "HB_SOUTH"]


def _interval_start_utc(df: pd.DataFrame) -> pd.Series:
    col = "Interval Start" if "Interval Start" in df.columns else "Time"
    return pd.to_datetime(df[col], utc=True)


class ErcotSource:
    """Wraps `gridstatus.Ercot`, sharing one throttle across every call."""

    def __init__(self, limiter: RateLimiter, client: Any | None = None) -> None:
        self._limiter = limiter
        self._client = client or gridstatus.Ercot()

    def _call(self, fn: Callable[..., pd.DataFrame], **kwargs: Any) -> pd.DataFrame:
        self._limiter.acquire()
        return fn(**kwargs)

    def _spp(self, day: date, market: str) -> pd.DataFrame:
        df = self._call(
            self._client.get_spp,
            date=pd.Timestamp(day),
            end=pd.Timestamp(day) + pd.Timedelta(days=1),
            market=market,
            locations=SETTLEMENT_POINTS,
            location_type="ALL",
        )
        return pd.DataFrame(
            {
                "interval_start_utc": _interval_start_utc(df),
                "settlement_point": df["Location"],
                "price_usd_per_mwh": df["SPP"],
            }
        )

    def fetch_rt_spp(self, day: date) -> pd.DataFrame:
        """RT Settlement Point Prices, report NP6-905-CD."""
        return self._spp(day, gridstatus.Markets.REAL_TIME_15_MIN.value)

    def fetch_dam_spp(self, day: date) -> pd.DataFrame:
        """DAM Settlement Point Prices, report NP4-190-CD."""
        return self._spp(day, gridstatus.Markets.DAY_AHEAD_HOURLY.value)

    def fetch_as_prices(self, day: date) -> pd.DataFrame:
        """DAM AS clearing prices, report NP4-188-CD (context only)."""
        df = self._call(self._client.get_as_prices, date=pd.Timestamp(day))
        df = df.copy()
        df["interval_start_utc"] = _interval_start_utc(df)
        return df

    def fetch_load_forecast(self, day: date) -> pd.DataFrame:
        """7-day load forecast by weather zone, report NP3-565-CD (latest vintage only)."""
        df = self._call(
            self._client.get_load_forecast,
            date=pd.Timestamp(day),
            end=pd.Timestamp(day) + pd.Timedelta(days=7),
        )
        df = df.copy()
        df["interval_start_utc"] = _interval_start_utc(df)
        return df

    def fetch_load_actual(self, day: date) -> pd.DataFrame:
        """Actual system load by weather zone."""
        df = self._call(self._client.get_load_by_weather_zone, date=pd.Timestamp(day))
        df = df.copy()
        df["interval_start_utc"] = _interval_start_utc(df)
        return df

    def fetch_wind(self, day: date) -> pd.DataFrame:
        """Wind actual/forecast, reports NP4-732-CD / NP4-742-CD."""
        df = self._call(
            self._client.get_wind_actual_and_forecast_hourly,
            date=pd.Timestamp(day),
            end=pd.Timestamp(day) + timedelta(days=1),
        )
        df = df.copy()
        df["interval_start_utc"] = _interval_start_utc(df)
        return df

    def fetch_solar(self, day: date) -> pd.DataFrame:
        """Solar actual/forecast, reports NP4-745-CD / NP4-737-CD."""
        df = self._call(
            self._client.get_solar_actual_and_forecast_hourly,
            date=pd.Timestamp(day),
            end=pd.Timestamp(day) + timedelta(days=1),
        )
        df = df.copy()
        df["interval_start_utc"] = _interval_start_utc(df)
        return df

    def fetch_outages(self, day: date) -> pd.DataFrame:
        """Hourly resource outage capacity, report NP3-233-CD."""
        df = self._call(
            self._client.get_hourly_resource_outage_capacity,
            date=pd.Timestamp(day),
            end=pd.Timestamp(day) + timedelta(days=1),
        )
        df = df.copy()
        df["interval_start_utc"] = _interval_start_utc(df)
        return df
