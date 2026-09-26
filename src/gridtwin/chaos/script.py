"""Scripted Chaos Scenarios: "at interval k, apply X for n intervals" over a window of a
replay day. Parsing and window selection are pure (Seam B); scenarios/*.yaml hold the
scripts and README documents the format."""

from datetime import date, datetime

import yaml
from pydantic import BaseModel, Field, model_validator

from gridtwin.chaos.models import ScenarioName


class ChaosStep(BaseModel, frozen=True):
    at_interval: int = Field(ge=0)  # index into the window, 0 = its first interval
    apply: ScenarioName
    for_intervals: int = Field(default=1, ge=1)  # then the controller clears it
    target: str | None = None  # None = the scenario picks (worker-kill: the busy worker)


class ScenarioWindow(BaseModel, frozen=True):
    from_interval: int = Field(default=0, ge=0)  # index into the day's Market Intervals
    intervals: int | None = Field(default=None, ge=1)  # None = to the end of the day


class ChaosScript(BaseModel, frozen=True):
    name: str
    description: str = ""
    settlement_point: str | None = None  # None = SETTLEMENT_POINT
    day: date | None = None  # a cached day; None = `fixture` (or FIXTURE_PATH)
    fixture: str | None = None
    window: ScenarioWindow = ScenarioWindow()
    steps: list[ChaosStep] = []

    @model_validator(mode="after")
    def _steps_inside_window(self) -> "ChaosScript":
        if self.window.intervals is not None:
            for step in self.steps:
                if step.at_interval >= self.window.intervals:
                    raise ValueError(
                        f"step at_interval={step.at_interval} is outside the "
                        f"{self.window.intervals}-interval window"
                    )
        return self


def parse_script(text: str) -> ChaosScript:
    return ChaosScript.model_validate(yaml.safe_load(text))


def select_window(interval_starts: list[datetime], window: ScenarioWindow) -> list[datetime]:
    end = None if window.intervals is None else window.from_interval + window.intervals
    selected = interval_starts[window.from_interval : end]
    if window.intervals is not None and len(selected) < window.intervals:
        raise ValueError(
            f"window wants {window.intervals} intervals from #{window.from_interval}, "
            f"the day has {len(interval_starts)}"
        )
    return selected
