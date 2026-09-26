"""The naive Strategy: full discharge at/above the high price threshold, full charge
at/below the low threshold, idle otherwise."""

from gridtwin.planner.models import FleetPlan, FleetState
from gridtwin.replay.models import MarketSnapshot


def naive_strategy(
    fleet_state: FleetState,
    snapshot: MarketSnapshot,
    discharge_threshold_usd: float,
    charge_threshold_usd: float,
) -> FleetPlan:
    price = snapshot.rt_price_usd_per_mwh
    if price >= discharge_threshold_usd:
        target_mw = fleet_state.discharge_headroom_mw
    elif price <= charge_threshold_usd:
        target_mw = -fleet_state.charge_headroom_mw
    else:
        target_mw = 0.0
    return FleetPlan(target_mw=target_mw, strategy="naive")
