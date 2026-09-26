"""Disaggregate a Fleet Plan's target into per-device Setpoints, proportional to headroom.

Pure and headroom-capped, so the result already is the Achievable Target:
`min(plan target, Fleet State headroom)` (CONTEXT.md).
"""

from gridtwin.fleet.device import headroom_mw
from gridtwin.fleet.models import DeviceState


def disaggregate(target_mw: float, devices: list[DeviceState]) -> dict[str, float]:
    if target_mw >= 0:
        capacities = {d.device_id: headroom_mw(d)[0] for d in devices}
    else:
        capacities = {d.device_id: headroom_mw(d)[1] for d in devices}

    total_capacity = sum(capacities.values())
    if total_capacity <= 0:
        return dict.fromkeys(capacities, 0.0)

    achievable = min(abs(target_mw), total_capacity)
    sign = 1.0 if target_mw >= 0 else -1.0
    return {
        device_id: sign * achievable * (capacity / total_capacity)
        for device_id, capacity in capacities.items()
    }
