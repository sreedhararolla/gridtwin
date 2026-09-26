"""Finds the worker that is running a Replay Run's in-flight dispatch, so a worker kill
lands mid-dispatch: the Shard activity dies with the worker and must be retried on the
survivor. Reads Temporal's pending children/activities; no history scans."""

import asyncio
import time
from datetime import datetime

from pydantic import BaseModel
from temporalio.api.enums.v1 import PendingActivityState
from temporalio.client import Client, WorkflowExecutionStatus

POLL_SECONDS = 0.02


class InFlightDispatch(BaseModel, frozen=True):
    interval_start: datetime
    worker: str  # Temporal worker identity == compose service name (worker-a, worker-b)
    activity_id: str


class RunNotRunning(Exception):
    pass


class NoDispatchSeen(Exception):
    pass


async def find_in_flight_dispatch(
    client: Client, run_id: str, target: str | None
) -> InFlightDispatch | None:
    replay = await client.get_workflow_handle(f"replay:{run_id}").describe()
    if replay.status != WorkflowExecutionStatus.RUNNING:
        raise RunNotRunning(f"replay run {run_id} is {replay.status}")
    prefix = f"interval:{run_id}:"
    for child in replay.raw_description.pending_children:
        if not child.workflow_id.startswith(prefix):
            continue
        interval = await client.get_workflow_handle(child.workflow_id).describe()
        for pending in interval.raw_description.pending_activities:
            worker = pending.last_worker_identity
            if (
                pending.activity_type.name == "dispatch_shard"
                and pending.state == PendingActivityState.PENDING_ACTIVITY_STATE_STARTED
                and worker
                and (target is None or worker == target)
            ):
                return InFlightDispatch(
                    interval_start=datetime.fromisoformat(child.workflow_id.removeprefix(prefix)),
                    worker=worker,
                    activity_id=pending.activity_id,
                )
    return None


async def wait_for_dispatch(
    client: Client, run_id: str, target: str | None, timeout_s: float
) -> InFlightDispatch:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        found = await find_in_flight_dispatch(client, run_id, target)
        if found is not None:
            return found
        await asyncio.sleep(POLL_SECONDS)
    raise NoDispatchSeen(f"no dispatch in flight for run {run_id} within {timeout_s:.0f} s")
