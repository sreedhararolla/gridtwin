"""Postgres connection, the service-heartbeat table, the dispatch ledger schema and the
chaos event log."""

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

CREATE TABLE IF NOT EXISTS devices (
    run_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    soc_pct DOUBLE PRECISION NOT NULL,
    energy_kwh DOUBLE PRECISION NOT NULL,
    max_power_kw DOUBLE PRECISION NOT NULL,
    round_trip_efficiency DOUBLE PRECISION NOT NULL,
    reserve_floor_pct DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, device_id)
);

-- Idempotency Key = run_id : interval_start : device_id : seq (CONTEXT.md). The primary
-- key is the dedupe boundary: a Command is applied at most once no matter how many times
-- it is delivered.
CREATE TABLE IF NOT EXISTS commands (
    idempotency_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    interval_start TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL,
    seq INT NOT NULL,
    setpoint_mw DOUBLE PRECISION NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    applied BOOLEAN,
    delivered_mw DOUBLE PRECISION,
    acked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS commands_run_id_idx ON commands (run_id);
-- Lifecycle: issued -> acked / expired / failed (the ledger summary groups by it).
ALTER TABLE commands ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'issued';

CREATE TABLE IF NOT EXISTS interval_results (
    run_id TEXT NOT NULL,
    interval_start TIMESTAMPTZ NOT NULL,
    settlement_point TEXT NOT NULL,
    price_usd_per_mwh DOUBLE PRECISION NOT NULL,
    target_mw DOUBLE PRECISION NOT NULL,
    achievable_mw DOUBLE PRECISION NOT NULL,
    delivered_mw DOUBLE PRECISION NOT NULL,
    level TEXT NOT NULL,
    dispatched_count INT NOT NULL,
    acked_count INT NOT NULL,
    reserve_violations INT NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, interval_start)
);
ALTER TABLE interval_results
    ADD COLUMN IF NOT EXISTS budget_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS online_devices INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS shard_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS soc_p10_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS soc_p50_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS soc_p90_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS duplicate_deliveries INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS duplicate_effects INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS retried_dispatches INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS planned_achievable_mw DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS stale_devices INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unresponsive_devices INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reallocation_rounds INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reallocated_mw DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reallocated_devices INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS feed_status TEXT NOT NULL DEFAULT 'ok',
    ADD COLUMN IF NOT EXISTS feed_detail TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS strategy TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS forecast_source TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS plan_mw DOUBLE PRECISION[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS reserve_floor_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reserve_reasons JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS member_card JSONB;

-- Telemetry: the latest Heartbeat per Device per run, batched in by the ingester.
CREATE TABLE IF NOT EXISTS device_telemetry (
    run_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    shard_id TEXT NOT NULL,
    soc_pct DOUBLE PRECISION NOT NULL,
    energy_kwh DOUBLE PRECISION NOT NULL,
    max_power_kw DOUBLE PRECISION NOT NULL,
    round_trip_efficiency DOUBLE PRECISION NOT NULL,
    reserve_floor_pct DOUBLE PRECISION NOT NULL,
    power_mw DOUBLE PRECISION NOT NULL,
    healthy BOOLEAN NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, device_id)
);

-- The chaos event log: every Chaos Scenario applied or cleared, with time and target.
CREATE TABLE IF NOT EXISTS chaos_events (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL,
    scenario TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    interval_start TIMESTAMPTZ,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS chaos_events_run_id_idx ON chaos_events (run_id);
"""


@contextmanager
def get_conn():
    with psycopg.connect(settings.postgres_dsn, connect_timeout=3, autocommit=True) as conn:
        yield conn


SCHEMA_LOCK_ID = 60_2026  # every service runs init_schema at boot; one at a time


def init_schema() -> None:
    # Concurrent ALTER TABLEs from services booting together deadlock; the advisory lock
    # serializes them (the multi-statement script runs as one implicit transaction).
    with get_conn() as conn:
        conn.execute(f"SELECT pg_advisory_xact_lock({SCHEMA_LOCK_ID});\n{SCHEMA}")


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
