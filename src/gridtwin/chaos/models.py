"""Chaos Scenario models at the controller/API boundary."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Ticket 05 ships worker-kill, 06 duplicate-commands, 07 partition and telemetry-delay,
# 08 the feed faults.
ScenarioName = Literal[
    "worker-kill",
    "duplicate-commands",
    "partition",
    "telemetry-delay",
    "feed-outage",
    "feed-outlier",
]
# Scenarios the chaos controller broadcasts to every simulator at once; this is their
# event-log target.
SIMULATOR_SCENARIOS = ("duplicate-commands", "partition", "telemetry-delay")
SIMULATORS_TARGET = "simulators"
# Feed faults live in the chaos event log itself: while one is applied for a run, the
# worker's feed read raises (outage) or returns the outlier price (outlier).
FEED_SCENARIOS = ("feed-outage", "feed-outlier")
FEED_TARGET = "ercot-feed"
FEED_OUTLIER_PRICE_USD = 9999.0
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
    # partition / telemetry-delay: the share of Devices hit (0-1); None = the default.
    pct: float | None = Field(default=None, ge=0.0, le=1.0)
    # telemetry-delay: how late Heartbeats arrive, wall seconds; None = the default.
    delay_s: float | None = Field(default=None, gt=0.0)


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
