"""Dependency health checks for the /health endpoint.

Each check is a best-effort liveness probe with a short timeout: a real query
for Postgres, a real protocol handshake for NATS, and a raw TCP connect for
Temporal (a full RPC round trip isn't needed to answer "is it reachable").
"""

import asyncio

import nats
import psycopg

from gridtwin.api.models import DependencyStatus, HealthResponse, ServiceCount
from gridtwin.ledger.db import live_instance_count
from gridtwin.settings import settings

TIMEOUT_SECONDS = 3.0


async def check_postgres() -> DependencyStatus:
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.postgres_dsn, connect_timeout=TIMEOUT_SECONDS
        ) as conn:
            await conn.execute("SELECT 1")
        return DependencyStatus(name="postgres", ok=True)
    except Exception as exc:  # noqa: BLE001 - report any failure as a down dependency
        return DependencyStatus(name="postgres", ok=False, detail=str(exc))


async def check_nats() -> DependencyStatus:
    try:
        nc = await asyncio.wait_for(
            nats.connect(settings.nats_url, allow_reconnect=False),
            timeout=TIMEOUT_SECONDS,
        )
        await nc.close()
        return DependencyStatus(name="nats", ok=True)
    except Exception as exc:  # noqa: BLE001
        return DependencyStatus(name="nats", ok=False, detail=str(exc))


async def check_temporal() -> DependencyStatus:
    host, _, port = settings.temporal_address.partition(":")
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port or 7233)), timeout=TIMEOUT_SECONDS
        )
        writer.close()
        await writer.wait_closed()
        return DependencyStatus(name="temporal", ok=True)
    except Exception as exc:  # noqa: BLE001
        return DependencyStatus(name="temporal", ok=False, detail=str(exc))


def service_counts() -> list[ServiceCount]:
    counts = []
    for name, total in (
        ("worker", settings.worker_replicas),
        ("simulator", settings.simulator_replicas),
    ):
        try:
            ready = live_instance_count(name, settings.heartbeat_stale_seconds)
        except Exception:  # noqa: BLE001 - postgres down means we can't count either
            ready = 0
        counts.append(ServiceCount(name=name, ready=ready, total=total))
    return counts


async def gather_health() -> HealthResponse:
    dependencies = list(await asyncio.gather(check_postgres(), check_nats(), check_temporal()))
    services = service_counts()
    core_ok = all(dep.ok for dep in dependencies)
    return HealthResponse(ok=core_ok, dependencies=dependencies, services=services)
