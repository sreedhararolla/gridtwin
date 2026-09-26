from datetime import date

from gridtwin.marketdata.ercot_public_api import (
    BASE_URL,
    LOAD_FORECAST_WEATHER_ZONE_REPORT,
    TOKEN_URL,
    ErcotPublicApiClient,
)
from gridtwin.marketdata.throttle import RateLimiter


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def post(self, url: str, data: dict) -> FakeResponse:
        self.calls.append(("POST", url, data))
        return FakeResponse({"id_token": "fake-token"})

    def get(self, url: str, params: dict, headers: dict) -> FakeResponse:
        self.calls.append(("GET", url, {"params": params, "headers": headers}))
        return FakeResponse({"data": [{"deliveryDate": "2025-12-10", "loadForecast": 42.0}]})


def _limiter() -> RateLimiter:
    clock = {"t": 0.0}
    return RateLimiter(
        max_calls=30, period_seconds=60.0, clock=lambda: clock["t"], sleep=lambda s: None
    )


def test_authenticates_once_then_reuses_the_token():
    http = FakeHttpClient()
    client = ErcotPublicApiClient(limiter=_limiter(), http_client=http)

    client.fetch_load_forecast_vintages(date(2025, 12, 10))
    client.fetch_load_forecast_vintages(date(2025, 12, 11))

    posts = [c for c in http.calls if c[0] == "POST"]
    assert len(posts) == 1
    assert posts[0][1] == TOKEN_URL


def test_sends_the_bearer_token_and_subscription_key(monkeypatch):
    monkeypatch.setattr(
        "gridtwin.marketdata.ercot_public_api.settings.ercot_api_subscription_key", "sub-key-123"
    )
    http = FakeHttpClient()
    client = ErcotPublicApiClient(limiter=_limiter(), http_client=http)

    client.fetch_load_forecast_vintages(date(2025, 12, 10))

    get_call = next(c for c in http.calls if c[0] == "GET")
    assert get_call[1] == f"{BASE_URL}/{LOAD_FORECAST_WEATHER_ZONE_REPORT}"
    headers = get_call[2]["headers"]
    assert headers["Authorization"] == "Bearer fake-token"
    assert headers["Ocp-Apim-Subscription-Key"] == "sub-key-123"


def test_returns_rows_as_a_dataframe():
    http = FakeHttpClient()
    client = ErcotPublicApiClient(limiter=_limiter(), http_client=http)

    df = client.fetch_load_forecast_vintages(date(2025, 12, 10))

    assert len(df) == 1
    assert df.iloc[0]["loadForecast"] == 42.0
