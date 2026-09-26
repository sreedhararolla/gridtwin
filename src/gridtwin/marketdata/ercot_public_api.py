"""The keyed ERCOT Public API (api.ercot.com): the one thing the keyless MIS
archives can't give us — every forecast *vintage* for a day, not just the
latest. Gated on `settings.ercot_api_configured`; without keys, `ingest.py`
never calls this and `data-audit` reports it `pending-credentials`.
"""

from datetime import date
from typing import Any

import httpx
import pandas as pd

from gridtwin.marketdata.throttle import RateLimiter
from gridtwin.settings import settings

TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
BASE_URL = "https://api.ercot.com/api/public-reports"
LOAD_FORECAST_WEATHER_ZONE_REPORT = "NP3-565-CD"
PUBLIC_API_CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"


class ErcotPublicApiClient:
    def __init__(self, limiter: RateLimiter, http_client: Any | None = None) -> None:
        self._limiter = limiter
        self._http = http_client or httpx.Client(timeout=15.0)
        self._token: str | None = None

    def _authenticate(self) -> str:
        if self._token is not None:
            return self._token
        self._limiter.acquire()
        response = self._http.post(
            TOKEN_URL,
            data={
                "grant_type": "password",
                "username": settings.ercot_api_username,
                "password": settings.ercot_api_password,
                "response_type": "id_token",
                "scope": f"openid {PUBLIC_API_CLIENT_ID} offline_access",
                "client_id": PUBLIC_API_CLIENT_ID,
            },
        )
        response.raise_for_status()
        self._token = response.json()["id_token"]
        return self._token

    def fetch_load_forecast_vintages(self, day: date) -> pd.DataFrame:
        """Every published vintage of the 7-day load forecast for `day`."""
        token = self._authenticate()
        self._limiter.acquire()
        response = self._http.get(
            f"{BASE_URL}/{LOAD_FORECAST_WEATHER_ZONE_REPORT}",
            params={"deliveryDateFrom": day.isoformat(), "deliveryDateTo": day.isoformat()},
            headers={
                "Authorization": f"Bearer {token}",
                "Ocp-Apim-Subscription-Key": settings.ercot_api_subscription_key,
            },
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
        df = pd.DataFrame(rows)
        if not df.empty and "interval_start_utc" not in df.columns:
            time_col = next(c for c in df.columns if "time" in c.lower() or "date" in c.lower())
            df["interval_start_utc"] = pd.to_datetime(df[time_col], utc=True)
        return df
