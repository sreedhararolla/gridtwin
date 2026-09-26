"""The chaos event log in Postgres, and the interval completion times Recovery Time is
measured against."""

from datetime import datetime

from gridtwin.chaos.models import FEED_SCENARIOS, ChaosEvent
from gridtwin.ledger.db import get_conn

EVENT_FIELDS = ["run_id", "at", "scenario", "action", "target", "interval_start", "detail"]
EVENT_COLUMNS = ", ".join(EVENT_FIELDS)


def record_event(event: ChaosEvent) -> None:
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO chaos_events ({EVENT_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            tuple(getattr(event, f) for f in EVENT_FIELDS),
        )


def list_events(run_id: str) -> list[ChaosEvent]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {EVENT_COLUMNS} FROM chaos_events WHERE run_id = %s ORDER BY at, id",
            (run_id,),
        ).fetchall()
    return [ChaosEvent(**dict(zip(EVENT_FIELDS, r, strict=True))) for r in rows]


def active_feed_faults(run_id: str, _interval_start: datetime | None = None) -> set[str]:
    """Feed Chaos Scenarios applied to this run and not yet cleared: the worker's feed read
    consults the event log itself, so the controller needs no line to the workers."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT ON (scenario) scenario, action FROM chaos_events
            WHERE run_id = %s AND scenario = ANY(%s)
            ORDER BY scenario, at DESC, id DESC
            """,
            (run_id, list(FEED_SCENARIOS)),
        ).fetchall()
    return {scenario for scenario, action in rows if action == "apply"}


def interval_completed_at(run_id: str) -> dict[datetime, datetime]:
    """interval_start -> when its Interval Result was recorded."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT interval_start, created_at FROM interval_results WHERE run_id = %s",
            (run_id,),
        ).fetchall()
    return {interval_start: created_at for interval_start, created_at in rows}
