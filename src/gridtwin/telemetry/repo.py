"""Telemetry store: the latest Heartbeat per Device per run (CONTEXT.md: Heartbeat,
Stale Device). Postgres in compose, in-memory for the Scenario Runner (Seam A)."""

from datetime import datetime
from typing import Protocol

from gridtwin.fleet.models import DeviceState, Heartbeat
from gridtwin.ledger.db import get_conn


class TelemetryRepo(Protocol):
    def upsert_heartbeats(self, heartbeats: list[Heartbeat]) -> None: ...
    def latest(self, run_id: str) -> list[Heartbeat]: ...


def _newer(candidate: Heartbeat, current: Heartbeat | None) -> bool:
    return current is None or candidate.sent_at >= current.sent_at


class LatestHeartbeats:
    """The ingester's buffer: keeps only the newest Heartbeat per (run, Device) between
    flushes, so a flush writes at most one row per Device however many arrived."""

    def __init__(self) -> None:
        self._latest: dict[tuple[str, str], Heartbeat] = {}

    def add(self, heartbeats: list[Heartbeat]) -> None:
        for hb in heartbeats:
            key = (hb.run_id, hb.state.device_id)
            if _newer(hb, self._latest.get(key)):
                self._latest[key] = hb

    def drain(self) -> list[Heartbeat]:
        batch = list(self._latest.values())
        self._latest.clear()
        return batch


class InMemoryTelemetryRepo:
    def __init__(self) -> None:
        self._latest: dict[str, dict[str, Heartbeat]] = {}

    def upsert_heartbeats(self, heartbeats: list[Heartbeat]) -> None:
        for hb in heartbeats:
            bucket = self._latest.setdefault(hb.run_id, {})
            if _newer(hb, bucket.get(hb.state.device_id)):
                bucket[hb.state.device_id] = hb

    def latest(self, run_id: str) -> list[Heartbeat]:
        return list(self._latest.get(run_id, {}).values())


class PostgresTelemetryRepo:
    def upsert_heartbeats(self, heartbeats: list[Heartbeat]) -> None:
        if not heartbeats:
            return
        with get_conn() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO device_telemetry
                    (run_id, device_id, shard_id, soc_pct, energy_kwh, max_power_kw,
                     round_trip_efficiency, reserve_floor_pct, power_mw, healthy, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, device_id) DO UPDATE SET
                    soc_pct = EXCLUDED.soc_pct,
                    power_mw = EXCLUDED.power_mw,
                    healthy = EXCLUDED.healthy,
                    sent_at = EXCLUDED.sent_at
                WHERE device_telemetry.sent_at <= EXCLUDED.sent_at
                """,
                [
                    (
                        hb.run_id,
                        hb.state.device_id,
                        hb.state.shard_id,
                        hb.state.soc_pct,
                        hb.state.energy_kwh,
                        hb.state.max_power_kw,
                        hb.state.round_trip_efficiency,
                        hb.state.reserve_floor_pct,
                        hb.power_mw,
                        hb.healthy,
                        hb.sent_at,
                    )
                    for hb in heartbeats
                ],
            )

    def latest(self, run_id: str) -> list[Heartbeat]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT device_id, shard_id, soc_pct, energy_kwh, max_power_kw,
                       round_trip_efficiency, reserve_floor_pct, power_mw, healthy, sent_at
                FROM device_telemetry WHERE run_id = %s
                """,
                (run_id,),
            ).fetchall()
        return [_row_to_heartbeat(run_id, r) for r in rows]


def _row_to_heartbeat(run_id: str, r: tuple) -> Heartbeat:
    sent_at: datetime = r[9]
    return Heartbeat(
        run_id=run_id,
        state=DeviceState(
            device_id=r[0],
            shard_id=r[1],
            soc_pct=r[2],
            energy_kwh=r[3],
            max_power_kw=r[4],
            round_trip_efficiency=r[5],
            reserve_floor_pct=r[6],
        ),
        power_mw=r[7],
        healthy=r[8],
        sent_at=sent_at,
    )
