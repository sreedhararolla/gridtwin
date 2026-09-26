"""Postgres connection and the service-heartbeat table.

Ticket 01 only needs heartbeats (liveness). The dispatch ledger tables
(commands, interval results, chaos events) land with later tickets.
"""

from contextlib import contextmanager
from datetime import UTC, datetime

import psycopg

from gridtwin.settings import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS service_heartbeats (
    service_name TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (service_name, instance_id)
);
"""


@contextmanager
def get_conn():
    with psycopg.connect(settings.postgres_dsn, connect_timeout=3, autocommit=True) as conn:
        yield conn


def init_schema() -> None:
    with get_conn() as conn:
        conn.execute(SCHEMA)


def record_heartbeat(service_name: str, instance_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO service_heartbeats (service_name, instance_id, last_seen)
            VALUES (%s, %s, %s)
            ON CONFLICT (service_name, instance_id)
            DO UPDATE SET last_seen = EXCLUDED.last_seen
            """,
            (service_name, instance_id, datetime.now(UTC)),
        )


def live_instance_count(service_name: str, stale_seconds: float) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT count(*) FROM service_heartbeats
            WHERE service_name = %s
              AND last_seen > now() - (%s || ' seconds')::interval
            """,
            (service_name, stale_seconds),
        ).fetchone()
        return row[0] if row else 0
