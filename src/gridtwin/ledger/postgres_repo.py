"""Postgres-backed LedgerRepo: idempotent upsert by Idempotency Key, plus results."""

from gridtwin.fleet.models import Ack, Command, DeviceState
from gridtwin.ledger.db import get_conn
from gridtwin.ledger.models import IntervalResult


class PostgresLedgerRepo:
    def seed_devices(self, run_id: str, devices: list[DeviceState]) -> None:
        with get_conn() as conn:
            for d in devices:
                conn.execute(
                    """
                    INSERT INTO devices
                        (run_id, device_id, soc_pct, energy_kwh, max_power_kw,
                         round_trip_efficiency, reserve_floor_pct, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (run_id, device_id) DO NOTHING
                    """,
                    (
                        run_id,
                        d.device_id,
                        d.soc_pct,
                        d.energy_kwh,
                        d.max_power_kw,
                        d.round_trip_efficiency,
                        d.reserve_floor_pct,
                    ),
                )

    def get_devices(self, run_id: str) -> list[DeviceState]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT device_id, soc_pct, energy_kwh, max_power_kw,
                       round_trip_efficiency, reserve_floor_pct
                FROM devices WHERE run_id = %s ORDER BY device_id
                """,
                (run_id,),
            ).fetchall()
        return [
            DeviceState(
                device_id=r[0],
                soc_pct=r[1],
                energy_kwh=r[2],
                max_power_kw=r[3],
                round_trip_efficiency=r[4],
                reserve_floor_pct=r[5],
            )
            for r in rows
        ]

    def upsert_command(self, command: Command) -> None:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO commands
                    (idempotency_key, run_id, interval_start, device_id, seq, setpoint_mw,
                     issued_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    command.idempotency_key,
                    command.run_id,
                    command.interval_start,
                    command.device_id,
                    command.seq,
                    command.setpoint_mw,
                ),
            )

    def record_ack(self, ack: Ack) -> None:
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE commands SET applied = %s, delivered_mw = %s, acked_at = now()
                WHERE idempotency_key = %s
                """,
                (ack.applied, ack.delivered_mw, ack.idempotency_key),
            )

    def update_device_soc(self, run_id: str, device_id: str, soc_pct: float) -> None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE devices SET soc_pct = %s, updated_at = now() "
                "WHERE run_id = %s AND device_id = %s",
                (soc_pct, run_id, device_id),
            )

    def record_interval_result(self, result: IntervalResult) -> None:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO interval_results
                    (run_id, interval_start, settlement_point, price_usd_per_mwh, target_mw,
                     achievable_mw, delivered_mw, level, dispatched_count, acked_count,
                     reserve_violations, latency_ms, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (run_id, interval_start) DO UPDATE SET
                    delivered_mw = EXCLUDED.delivered_mw,
                    acked_count = EXCLUDED.acked_count,
                    reserve_violations = EXCLUDED.reserve_violations
                """,
                (
                    result.run_id,
                    result.interval_start,
                    result.settlement_point,
                    result.price_usd_per_mwh,
                    result.target_mw,
                    result.achievable_mw,
                    result.delivered_mw,
                    result.level,
                    result.dispatched_count,
                    result.acked_count,
                    result.reserve_violations,
                    result.latency_ms,
                ),
            )

    def list_interval_results(self, run_id: str) -> list[IntervalResult]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT run_id, interval_start, settlement_point, price_usd_per_mwh, target_mw,
                       achievable_mw, delivered_mw, level, dispatched_count, acked_count,
                       reserve_violations, latency_ms
                FROM interval_results WHERE run_id = %s ORDER BY interval_start
                """,
                (run_id,),
            ).fetchall()
        return [
            IntervalResult(
                run_id=r[0],
                interval_start=r[1],
                settlement_point=r[2],
                price_usd_per_mwh=r[3],
                target_mw=r[4],
                achievable_mw=r[5],
                delivered_mw=r[6],
                level=r[7],
                dispatched_count=r[8],
                acked_count=r[9],
                reserve_violations=r[10],
                latency_ms=r[11],
            )
            for r in rows
        ]

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
