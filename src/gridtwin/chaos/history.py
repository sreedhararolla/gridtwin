"""Reads Temporal history for the evidence a worker kill leaves behind: the killed
dispatch attempt and the retry that completed on another worker."""

from datetime import datetime

from pydantic import BaseModel
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client


class ActivityAttempt(BaseModel, frozen=True):
    workflow_id: str
    activity_id: str
    attempt: int
    worker: str
    completed: bool


async def dispatch_attempts(
    client: Client, run_id: str, interval_start: datetime
) -> list[ActivityAttempt]:
    """The final attempt of every dispatch activity in one Market Interval.

    Temporal records a retried activity as one ActivityTaskStarted carrying the attempt
    number and the identity of the worker that ran it."""
    workflow_id = f"interval:{run_id}:{interval_start.isoformat()}"
    handle = client.get_workflow_handle(workflow_id)
    scheduled: dict[int, str] = {}
    started: dict[int, tuple[int, str]] = {}
    completed: set[int] = set()
    async for event in handle.fetch_history_events():
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            scheduled[event.event_id] = event.activity_task_scheduled_event_attributes.activity_id
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED:
            attrs = event.activity_task_started_event_attributes
            started[attrs.scheduled_event_id] = (attrs.attempt, attrs.identity)
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            completed.add(event.activity_task_completed_event_attributes.scheduled_event_id)
    return [
        ActivityAttempt(
            workflow_id=workflow_id,
            activity_id=activity_id,
            attempt=started[event_id][0],
            worker=started[event_id][1],
            completed=event_id in completed,
        )
        for event_id, activity_id in scheduled.items()
        if activity_id.startswith("dispatch:") and event_id in started
    ]
