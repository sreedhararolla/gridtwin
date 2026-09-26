import logging

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from gridtwin.api import chaos, insights, marketdata, runs
from gridtwin.api.health import gather_health
from gridtwin.api.models import HealthResponse
from gridtwin.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="GridTwin API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    result = await gather_health()
    if not result.ok:
        response.status_code = 503
    return result


app.include_router(runs.router)
app.include_router(marketdata.router)
app.include_router(chaos.router)
app.include_router(insights.router)
