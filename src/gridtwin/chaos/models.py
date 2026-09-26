"""Chaos Scenario models at the controller/API boundary."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Ticket 05 ships worker-kill, 06 duplicate-commands; 07-08 add device, telemetry and feed
# faults.
ScenarioName = Literal["worker-kill", "duplicate-commands"]
# duplicate-commands hits every simulator at once; this is its event-log target.
SIMULATORS_TARGET = "simulators"
ChaosAction = Literal["apply", "clear"]


class ChaosEvent(BaseModel, frozen=True):
    """One row of the chaos event log: when, which scenario, against what."""

    run_id: str
    at: datetime
    scenario: str
    action: ChaosAction
    target: str
    # The Market Interval the fault hit, when it hit one (worker-kill: the interval whose
    # dispatch was in flight). Recovery Time is measured against this interval's result.
    interval_start: datetime | None = None
    detail: str = ""


class ApplyChaosRequest(BaseModel):
    scenario: ScenarioName
    run_id: str
    # worker-kill: a worker instance (`worker-a`), or None = whichever worker is running
    # the in-flight dispatch. duplicate-commands: ignored (all simulators).
    target: str | None = None
    # How long the fault lasts before the controller clears it; None = the default.
    duration_s: float | None = None


class ClearChaosRequest(BaseModel):
    scenario: ScenarioName
    run_id: str
    # worker-kill: the worker instance to restart now; duplicate-commands: "simulators".
    target: str = SIMULATORS_TARGET


class RecoveryTime(BaseModel, frozen=True):
    at: datetime
    scenario: str
    target: str
    interval_start: datetime
    recovery_s: float | None  # None = the interrupted interval never completed


class SloRow(BaseModel, frozen=True):
    name: str
    target: str
    actual: str
    ok: bool


class SloReport(BaseModel, frozen=True):
    run_id: str
    rows: list[SloRow]
    recoveries: list[RecoveryTime]
