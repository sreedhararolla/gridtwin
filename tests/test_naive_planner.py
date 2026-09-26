from datetime import UTC, datetime

from gridtwin.planner.models import FleetState
from gridtwin.planner.naive import naive_strategy
from gridtwin.replay.models import MarketSnapshot

FLEET_STATE = FleetState(discharge_headroom_mw=0.05, charge_headroom_mw=0.05, devices=[])


def snapshot(price: float) -> MarketSnapshot:
    return MarketSnapshot(
        interval_start=datetime(2025, 12, 10, 12, 0, tzinfo=UTC),
        settlement_point="LZ_HOUSTON",
        rt_price_usd_per_mwh=price,
    )


def test_discharges_at_or_above_threshold():
    plan = naive_strategy(
        FLEET_STATE, snapshot(90.0), discharge_threshold_usd=90.0, charge_threshold_usd=20.0
    )
    assert plan.target_mw == FLEET_STATE.discharge_headroom_mw


def test_charges_at_or_below_threshold():
    plan = naive_strategy(
        FLEET_STATE, snapshot(20.0), discharge_threshold_usd=90.0, charge_threshold_usd=20.0
    )
    assert plan.target_mw == -FLEET_STATE.charge_headroom_mw


def test_idles_between_thresholds():
    plan = naive_strategy(
        FLEET_STATE, snapshot(55.0), discharge_threshold_usd=90.0, charge_threshold_usd=20.0
    )
    assert plan.target_mw == 0.0
