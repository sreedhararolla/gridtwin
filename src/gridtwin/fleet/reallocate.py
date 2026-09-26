"""Reallocation (CONTEXT.md): re-issue a Market Interval's Shortfall to Devices that still
have Headroom, as `seq+1` Commands. Pure; the workflow drives the bounded rounds.

A Device that did not answer its Command (a partition, a dead link) is treated as stale for
the rest of the interval: it is not a Reallocation candidate, and the Achievable Target is
re-rated without it. That is the same rule Fleet State applies one telemetry period later,
applied as soon as the missing Ack is evidence enough (docs/DECISIONS.md, ADR-012).
"""

from pydantic import BaseModel, Field

from gridtwin.fleet.device import headroom_mw, remaining_headroom_mw
from gridtwin.fleet.models import DeviceState
from gridtwin.planner.models import FleetState


class ReallocationConfig(BaseModel, frozen=True):
    """Step 6 of the interval flow: at most `max_rounds` seq+1 rounds, each started only
    while less than `deadline_pct` of the interval's wall budget has gone.

    `reserve_pct` of Fleet State headroom is held back from the planner, the way a VPP
    holds operating reserve: without it a full-discharge plan leaves every Device at its
    limit and a Shortfall has nowhere to go (ADR-012)."""

    tolerance_pct: float = 0.05
    max_rounds: int = Field(default=2, ge=0)
    deadline_pct: float = Field(default=0.5, ge=0.0, le=1.0)
    reserve_pct: float = Field(default=0.10, ge=0.0, lt=1.0)


def with_reserve(fleet_state: FleetState, reserve_pct: float) -> FleetState:
    """The Fleet State the planner sees: headroom less the reallocation reserve, and no
    per-Device list (the planner needs aggregates only)."""
    keep = 1.0 - reserve_pct
    return fleet_state.model_copy(
        update={
            "discharge_headroom_mw": fleet_state.discharge_headroom_mw * keep,
            "charge_headroom_mw": fleet_state.charge_headroom_mw * keep,
            "devices": [],
        }
    )


def rerate_achievable(
    target_mw: float, devices: list[DeviceState], unresponsive: set[str]
) -> float:
    """Achievable Target = min(plan target, headroom of the Devices still reachable)."""
    discharge = target_mw >= 0
    reachable_mw = sum(
        headroom_mw(d)[0 if discharge else 1] for d in devices if d.device_id not in unresponsive
    )
    achievable = min(abs(target_mw), reachable_mw)
    return achievable if discharge else -achievable


def reallocation_headroom(
    devices: list[DeviceState], delivered: dict[str, float], discharge: bool
) -> dict[str, float]:
    """Headroom left this interval for each Device that acted on its Command. `delivered`
    holds only Devices whose Acks came back applied, keyed by device id (signed MW)."""
    by_id = {d.device_id: d for d in devices}
    headroom = {}
    for device_id, delivered_mw in delivered.items():
        state = by_id.get(device_id)
        if state is None:
            continue
        left = remaining_headroom_mw(state, delivered_mw, discharge)
        if left > 0:
            headroom[device_id] = left
    return headroom


def reallocate(shortfall_mw: float, headroom: dict[str, float]) -> dict[str, float]:
    """Split a signed Shortfall across Devices in proportion to their remaining headroom.

    Returns the extra MW per Device (same sign as the Shortfall), each capped at that
    Device's headroom, summing to at most |shortfall|. Devices with nothing to add are
    left out, so the result is exactly the set of `seq+1` Commands to send."""
    total = sum(headroom.values())
    if shortfall_mw == 0 or total <= 0:
        return {}
    moved = min(abs(shortfall_mw), total)
    sign = 1.0 if shortfall_mw > 0 else -1.0
    return {
        device_id: sign * moved * (capacity / total)
        for device_id, capacity in headroom.items()
        if capacity > 0
    }


def needs_reallocation(
    achievable_mw: float, delivered_mw: float, tolerance_pct: float, floor_mw: float = 0.001
) -> bool:
    """The Shortfall is worth a round only when it is outside tolerance (docs/SPEC.md step
    6): ±tolerance of the Achievable Target, or `floor_mw` if larger (ADR-010)."""
    shortfall = achievable_mw - delivered_mw
    # Only chase a shortfall in the target's direction: over-delivery is not re-dispatched.
    if (achievable_mw >= 0 and shortfall <= 0) or (achievable_mw < 0 and shortfall >= 0):
        return False
    return abs(shortfall) > max(tolerance_pct * abs(achievable_mw), floor_mw)
