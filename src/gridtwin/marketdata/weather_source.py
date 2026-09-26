"""Open-Meteo hourly temperature: keyless, no throttle published, works from
anywhere (unlike ercot.com in this build environment; see docs/DECISIONS.md).
"""

from datetime import date

import httpx
import pandas as pd

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

WEATHER_CITIES = {
    "houston": (29.76, -95.37),
    "dfw": (32.90, -97.04),
    "austin": (30.27, -97.74),
    "san_antonio": (29.42, -98.49),
}


def fetch_temperature(
    city: str, day: date, http_client: httpx.Client | None = None
) -> pd.DataFrame:
    lat, lon = WEATHER_CITIES[city]
    client = http_client or httpx
    response = client.get(
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "hourly": "temperature_2m",
            "timezone": "UTC",
        },
        timeout=15.0,
    )
    response.raise_for_status()
    hourly = response.json()["hourly"]
    return pd.DataFrame(
        {
            "interval_start_utc": pd.to_datetime(hourly["time"], utc=True),
            "city": city,
            "temperature_c": hourly["temperature_2m"],
        }
    )
