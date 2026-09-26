"""Every dataset the spec's Data decisions section lists, in one place, so
`ingest`, `data-audit` and DATA.md all walk the same list.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd

from gridtwin.marketdata.ercot_public_api import ErcotPublicApiClient
from gridtwin.marketdata.ercot_source import ErcotSource
from gridtwin.marketdata.throttle import RateLimiter
from gridtwin.marketdata.weather_source import WEATHER_CITIES, fetch_temperature


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    report_id: str
    credential_gated: bool
    keys: tuple[str, ...]
    fetch: Callable[[str, date], pd.DataFrame]


def build_registry(ercot: ErcotSource, public_api: ErcotPublicApiClient) -> list[DatasetSpec]:
    return [
        DatasetSpec(
            "rt_spp", "NP6-905-CD", False, ("ALL",), lambda _key, day: ercot.fetch_rt_spp(day)
        ),
        DatasetSpec(
            "dam_spp", "NP4-190-CD", False, ("ALL",), lambda _key, day: ercot.fetch_dam_spp(day)
        ),
        DatasetSpec(
            "as_prices_dam",
            "NP4-188-CD",
            False,
            ("ALL",),
            lambda _key, day: ercot.fetch_as_prices(day),
        ),
        DatasetSpec(
            "load_forecast",
            "NP3-565-CD",
            False,
            ("ALL",),
            lambda _key, day: ercot.fetch_load_forecast(day),
        ),
        DatasetSpec(
            "load_actual",
            "NP3-565-CD",
            False,
            ("ALL",),
            lambda _key, day: ercot.fetch_load_actual(day),
        ),
        DatasetSpec(
            "wind",
            "NP4-732-CD/NP4-742-CD",
            False,
            ("ALL",),
            lambda _key, day: ercot.fetch_wind(day),
        ),
        DatasetSpec(
            "solar",
            "NP4-745-CD/NP4-737-CD",
            False,
            ("ALL",),
            lambda _key, day: ercot.fetch_solar(day),
        ),
        DatasetSpec(
            "outages", "NP3-233-CD", False, ("ALL",), lambda _key, day: ercot.fetch_outages(day)
        ),
        DatasetSpec(
            "load_forecast_vintages",
            "NP3-565-CD (all vintages)",
            True,
            ("ALL",),
            lambda _key, day: public_api.fetch_load_forecast_vintages(day),
        ),
        DatasetSpec(
            "weather_temperature",
            "Open-Meteo hourly",
            False,
            tuple(WEATHER_CITIES),
            lambda key, day: fetch_temperature(key, day),
        ),
    ]


def default_registry() -> list[DatasetSpec]:
    from gridtwin.settings import settings

    limiter = RateLimiter(
        max_calls=settings.ercot_throttle_per_minute,
        period_seconds=60.0,
        clock=time.monotonic,
        sleep=time.sleep,
    )
    return build_registry(ErcotSource(limiter), ErcotPublicApiClient(limiter))
