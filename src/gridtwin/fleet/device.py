"""Simple SoC physics for a Base Core battery, with the Reserve Floor enforced on the
device (defense in depth: the planner and the disaggregator also enforce it)."""

from gridtwin.fleet.models import Ack, Command, DeviceState

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


def apply_command(
    state: DeviceState, command: Command, response_factor: float = 1.0, faulted: bool = False
) -> tuple[DeviceState, Ack]:
    """Apply one Setpoint for one Market Interval and return the Device's new state and Ack.

    `response_factor` is the device's response noise (delivered = setpoint x factor, still
    capped at headroom so noise can never push SoC below the floor); `faulted` means the
    device failed to act at all. Both are drawn by the (seeded) simulator, keeping this pure.
    """
    if faulted:
        return state, Ack(
            idempotency_key=command.idempotency_key,
            device_id=state.device_id,
            applied=False,
            delivered_mw=0.0,
            soc_pct_after=state.soc_pct,
        )

    discharge_mw, charge_mw = headroom_mw(state)
    setpoint_mw = command.setpoint_mw * max(response_factor, 0.0)
    soc_kwh = state.energy_kwh * state.soc_pct

    if setpoint_mw >= 0:
        delivered_mw = min(setpoint_mw, discharge_mw)
        soc_kwh -= delivered_mw * 1000.0 * INTERVAL_HOURS
    else:
        charged_mw = min(-setpoint_mw, charge_mw)
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
