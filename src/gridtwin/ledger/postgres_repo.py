"""Postgres-backed LedgerRepo: idempotent upsert by Idempotency Key, plus results.

Every Shard batch write is one connection and one statement over arrays (`unnest`), so a
batch costs one round trip and one commit, not one per row."""

from gridtwin.fleet.models import Ack, Command, DeviceState
from gridtwin.ledger.db import get_conn
from gridtwin.ledger.models import (
    IntervalResult,
    LedgerIntervalSummary,
    command_status,
    summarize_ledger,
)

RESULT_COLUMNS = (
    "run_id, interval_start, settlement_point, price_usd_per_mwh, target_mw, achievable_mw, "
    "delivered_mw, level, dispatched_count, acked_count, reserve_violations, latency_ms, "
    "budget_ms, online_devices, shard_count, soc_p10_pct, soc_p50_pct, soc_p90_pct, "
    "duplicate_deliveries, duplicate_effects, retried_dispatches, planned_achievable_mw, "
    "stale_devices, unresponsive_devices, reallocation_rounds, reallocated_mw, "
    "reallocated_devices, feed_status, feed_detail, strategy, forecast_source, plan_mw"
)
RESULT_FIELDS = [c.strip() for c in RESULT_COLUMNS.split(",")]


class PostgresLedgerRepo:
    def seed_devices(self, run_id: str, devices: list[DeviceState]) -> None:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO devices
                    (run_id, device_id, soc_pct, energy_kwh, max_power_kw,
                     round_trip_efficiency, reserve_floor_pct, updated_at)
                SELECT %s, d, soc, e, p, rte, floor, now()
                FROM unnest(%s::text[], %s::float8[], %s::float8[], %s::float8[],
                            %s::float8[], %s::float8[]) AS x(d, soc, e, p, rte, floor)
                ON CONFLICT (run_id, device_id) DO NOTHING
                """,
                (
                    run_id,
                    [d.device_id for d in devices],
                    [d.soc_pct for d in devices],
                    [d.energy_kwh for d in devices],
                    [d.max_power_kw for d in devices],
                    [d.round_trip_efficiency for d in devices],
                    [d.reserve_floor_pct for d in devices],
                ),
            )

    def upsert_commands(self, commands: list[Command]) -> None:
        if not commands:
            return
        # One statement over arrays: executemany costs a round trip per row (ticket 12).
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO commands
                    (idempotency_key, run_id, interval_start, device_id, seq, setpoint_mw,
                     issued_at)
                SELECT k, r, i, d, s, mw, now()
                FROM unnest(%s::text[], %s::text[], %s::timestamptz[], %s::text[],
                            %s::int[], %s::float8[]) AS c(k, r, i, d, s, mw)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    [c.idempotency_key for c in commands],
                    [c.run_id for c in commands],
                    [c.interval_start for c in commands],
                    [c.device_id for c in commands],
                    [c.seq for c in commands],
                    [c.setpoint_mw for c in commands],
                ),
            )

    def record_acks(self, acks: list[Ack]) -> None:
        if not acks:
            return
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE commands
                SET applied = a.applied, delivered_mw = a.mw, status = a.status,
                    acked_at = now()
                FROM unnest(%s::text[], %s::bool[], %s::float8[], %s::text[])
                    AS a(k, applied, mw, status)
                WHERE idempotency_key = a.k
                """,
                (
                    [a.idempotency_key for a in acks],
                    [a.applied for a in acks],
                    [a.delivered_mw for a in acks],
                    [command_status(a.outcome) for a in acks],
                ),
            )

    def ledger_summary(self, run_id: str) -> list[LedgerIntervalSummary]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT interval_start, status, coalesce(delivered_mw, 0)
                FROM commands WHERE run_id = %s
                """,
                (run_id,),
            ).fetchall()
        return summarize_ledger([(r[0], r[1], r[2]) for r in rows])

    def record_interval_result(self, result: IntervalResult) -> None:
        placeholders = ", ".join(["%s"] * len(RESULT_FIELDS))
        with get_conn() as conn:
            conn.execute(
                f"""
                INSERT INTO interval_results ({RESULT_COLUMNS}, created_at)
                VALUES ({placeholders}, now())
                ON CONFLICT (run_id, interval_start) DO UPDATE SET
                    delivered_mw = EXCLUDED.delivered_mw,
                    acked_count = EXCLUDED.acked_count,
                    reserve_violations = EXCLUDED.reserve_violations,
                    duplicate_deliveries = EXCLUDED.duplicate_deliveries,
                    duplicate_effects = EXCLUDED.duplicate_effects,
                    retried_dispatches = EXCLUDED.retried_dispatches,
                    achievable_mw = EXCLUDED.achievable_mw,
                    unresponsive_devices = EXCLUDED.unresponsive_devices,
                    reallocation_rounds = EXCLUDED.reallocation_rounds,
                    reallocated_mw = EXCLUDED.reallocated_mw,
                    reallocated_devices = EXCLUDED.reallocated_devices
                """,
                tuple(getattr(result, f) for f in RESULT_FIELDS),
            )

    def list_interval_results(self, run_id: str) -> list[IntervalResult]:
        with get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT {RESULT_COLUMNS}
                FROM interval_results WHERE run_id = %s ORDER BY interval_start
                """,
                (run_id,),
            ).fetchall()
        return [IntervalResult(**dict(zip(RESULT_FIELDS, r, strict=True))) for r in rows]

    def command_counts(self, run_id: str) -> tuple[int, int]:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT count(*), count(*) FILTER (WHERE applied IS NOT NULL)
                FROM commands WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def latest_run_id(self) -> str | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT run_id FROM devices ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None
