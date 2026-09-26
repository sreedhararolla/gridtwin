"""Simple SoC physics for a Base Core battery, with the Reserve Floor enforced on the
device (defense in depth: the planner and the disaggregator also enforce it)."""

from datetime import datetime
from typing import Literal

from gridtwin.fleet.models import Ack, AckOutcome, Command, DeviceState

INTERVAL_HOURS = 0.25
FLOOR_EPSILON = 1e-9
MIN_HEADROOM_MW = 1e-6  # 1 W; Acks report delivered MW to 6 decimals


def headroom_mw(state: DeviceState) -> tuple[float, float]:
    """Return (discharge_headroom_mw, charge_headroom_mw) for this Market Interval, both >= 0."""
    usable_kwh_above_floor = max(state.energy_kwh * (state.soc_pct - state.reserve_floor_pct), 0.0)
    usable_kwh_to_full = max(state.energy_kwh * (1.0 - state.soc_pct), 0.0)
    discharge_mw = min(state.max_power_kw, usable_kwh_above_floor / INTERVAL_HOURS) / 1000.0
    charge_mw = min(state.max_power_kw, usable_kwh_to_full / INTERVAL_HOURS) / 1000.0
    # Float dust left at the floor or at full is not dispatchable headroom.
    return (
        discharge_mw if discharge_mw >= MIN_HEADROOM_MW else 0.0,
        charge_mw if charge_mw >= MIN_HEADROOM_MW else 0.0,
    )


def aggregate_headroom(devices: list[DeviceState]) -> tuple[float, float]:
    """Fleet State: aggregate available discharge/charge power above floor."""
    discharge_total = 0.0
    charge_total = 0.0
    for device in devices:
        discharge_mw, charge_mw = headroom_mw(device)
        discharge_total += discharge_mw
        charge_total += charge_mw
    return discharge_total, charge_total


CommandVerdict = Literal["apply", "duplicate", "expired", "superseded"]


def screen_command(
    command: Command,
    already_answered: bool,
    device_clock: datetime | None,
    latest_seq: int | None,
) -> CommandVerdict:
    """Decide whether a Device may act on a delivered Command (exactly-once effects).

    `already_answered`: this Device has already acted on this Idempotency Key (or tried
    to and faulted); it replays that answer instead of acting again.
    `device_clock`: the latest Market Interval this Device has acted in; a Command whose
    expiry is at or before it arrived late (e.g. a replayed old batch) and is ignored.
    `latest_seq`: the highest seq this Device has acted on for the Command's interval; a
    lower seq has been superseded by a Reallocation.
    """
    if already_answered:
        return "duplicate"
    if device_clock is not None and command.expires_at <= device_clock:
        return "expired"
    if latest_seq is not None and command.seq < latest_seq:
        return "superseded"
    return "apply"


def ignored_ack(state: DeviceState, command: Command, outcome: AckOutcome) -> Ack:
    """The Ack for a Command the Device did not act on: nothing delivered, SoC unchanged."""
    return Ack(
        idempotency_key=command.idempotency_key,
        device_id=state.device_id,
        applied=False,
        delivered_mw=0.0,
        soc_pct_after=state.soc_pct,
        outcome=outcome,
    )


def remaining_headroom_mw(state: DeviceState, delivered_mw: float, discharge: bool) -> float:
    """Headroom left this interval for a Device that was at `state` when the interval was
    planned and has since delivered `delivered_mw` (signed). Conservative: whatever it
    delivered comes off both its power and its energy headroom (a charge's efficiency loss
    only makes the true figure larger), so a Reallocation never over-commits it."""
    discharge_mw, charge_mw = headroom_mw(state)
    if discharge:
        return max(discharge_mw - max(delivered_mw, 0.0), 0.0)
    return max(charge_mw - max(-delivered_mw, 0.0), 0.0)


def apply_command(
    state: DeviceState,
    command: Command,
    response_factor: float = 1.0,
    faulted: bool = False,
    interval_delivered_mw: float = 0.0,
) -> tuple[DeviceState, Ack]:
    """Apply one Setpoint for one Market Interval and return the Device's new state and Ack.

    `response_factor` is the device's response noise (delivered = setpoint x factor, still
    capped at headroom so noise can never push SoC below the floor); `faulted` means the
    device failed to act at all. Both are drawn by the (seeded) simulator, keeping this pure.

    `interval_delivered_mw` is what this Device already delivered in the Command's interval
    (a lower seq). A Reallocation's `seq+1` Setpoint is the Device's new *total* for the
    interval, so it delivers only the increment, and the interval's total power stays within
    `max_power_kw` (the energy cap already reflects the SoC the earlier seq used).
    """
    if faulted:
        return state, ignored_ack(state, command, "failed")

    discharge_mw, charge_mw = headroom_mw(state)
    setpoint_mw = command.setpoint_mw * max(response_factor, 0.0)
    soc_kwh = state.energy_kwh * state.soc_pct
    max_mw = state.max_power_kw / 1000.0

    if setpoint_mw >= 0:
        already_mw = max(interval_delivered_mw, 0.0)
        power_left_mw = max(max_mw - already_mw, 0.0)
        delivered_mw = max(min(setpoint_mw - already_mw, discharge_mw, power_left_mw), 0.0)
        soc_kwh -= delivered_mw * 1000.0 * INTERVAL_HOURS
    else:
        already_mw = max(-interval_delivered_mw, 0.0)
        power_left_mw = max(max_mw - already_mw, 0.0)
        charged_mw = max(min(-setpoint_mw - already_mw, charge_mw, power_left_mw), 0.0)
        delivered_mw = -charged_mw
        soc_kwh += charged_mw * 1000.0 * INTERVAL_HOURS * state.round_trip_efficiency

    raw_soc_pct = soc_kwh / state.energy_kwh
    # A violation is *discharging* into the floor; a device already below it (and told to
    # hold or charge) is not violating anything by existing.
    floor_violation = delivered_mw > 0 and raw_soc_pct < state.reserve_floor_pct - FLOOR_EPSILON
    new_soc_pct = min(max(raw_soc_pct, 0.0), 1.0)

    new_state = state.model_copy(update={"soc_pct": new_soc_pct})
    ack = Ack(
        idempotency_key=command.idempotency_key,
        device_id=state.device_id,
        applied=True,
        delivered_mw=round(delivered_mw, 6),
        soc_pct_after=new_soc_pct,
        floor_violation=floor_violation,
    )
    return new_state, ack
