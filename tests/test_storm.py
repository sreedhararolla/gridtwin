"""Seam B: Storm mode (pure, no IO). The Dynamic Reserve Floor rises ahead of a tight
interval, the Member Card is derived from the computed Reserve Reasons, and the trade-off
panel's numbers are the backtest's own lp vs lp_storm values and schedules."""

from datetime import UTC, date, datetime, timedelta

import pytest

from gridtwin.fleet.device import apply_command
from gridtwin.fleet.models import Command, DeviceState
from gridtwin.planner.backtest import (
    backtest_day_schedules,
    lp_storm_schedule,
    start_soc,
    storm_day,
)
from gridtwin.planner.lp import FleetAggregate, LpConfig, solve, terminal_value
from gridtwin.storm.reserve import (
    ReserveReason,
    StormConfig,
    StormSignals,
    decide_reserve,
    member_card,
)

CONFIG = StormConfig(enabled=True, storm_floor_pct=0.6, risk_threshold=0.25, lead_intervals=8)
BASE = 0.2
LP = LpConfig()
FLEET = FleetAggregate(
    max_discharge_mw=20.0,
    max_charge_mw=20.0,
    capacity_mwh=78.4,
    floor_mwh=78.4 * BASE,
    energy_mwh=78.4 * 0.5,
    round_trip_efficiency=0.9,
)
# 23:00 UTC = 17:00 CST on a winter evening.
EVENING = datetime(2026, 1, 28, 23, 0, tzinfo=UTC)


def curve(tight_at: int, p: float = 0.6, length: int = 16) -> list[float]:
    return [p if t == tight_at else 0.01 for t in range(length)]


def test_floor_stays_at_base_when_storm_mode_is_off():
    decision = decide_reserve(StormSignals(p_spike=curve(0)), BASE, StormConfig())
    assert decision.floor_pct == BASE and not decision.raised and decision.reasons == []


def test_floor_rises_lead_intervals_before_a_tight_interval():
    far = decide_reserve(StormSignals(p_spike=curve(12)), BASE, CONFIG)
    assert far.floor_pct == BASE and far.reasons == []
    # The curve still sees it: the floor rises at offset 12 - 8 = 4, and stays through 12.
    assert far.floor_by_interval_pct[:4] == [BASE] * 4
    assert far.floor_by_interval_pct[4:13] == [0.6] * 9
    assert far.floor_by_interval_pct[13:] == [BASE] * 3

    near = decide_reserve(StormSignals(p_spike=curve(6)), BASE, CONFIG)
    assert near.floor_pct == 0.6 and near.raised
    assert near.reasons == [
        ReserveReason(kind="grid_tight", value=0.6, threshold=0.25, lead_intervals=6)
    ]


def test_weather_and_outages_raise_the_floor_for_the_whole_horizon():
    decision = decide_reserve(
        StormSignals(p_spike=[0.0] * 16, temperature_c=-8.0, outage_mw=25_000.0), BASE, CONFIG
    )
    assert decision.floor_pct == 0.6
    assert decision.floor_by_interval_pct == [0.6] * 16
    assert [r.kind for r in decision.reasons] == ["outages", "cold"]
    mild = decide_reserve(StormSignals(temperature_c=20.0, outage_mw=5_000.0), BASE, CONFIG)
    assert not mild.raised


def test_member_card_text_is_derived_from_the_computed_reasons():
    decision = decide_reserve(
        StormSignals(p_spike=curve(6, p=0.42), temperature_c=37.4), BASE, CONFIG
    )
    card = member_card(decision, EVENING, 39.2, CONFIG)
    assert card is not None
    # 17:00 CST + 6 intervals = 18:30 CT, an evening.
    assert card.headline == "Why is your battery at 60% tonight?"
    assert card.reasons == [
        "ERCOT's grid looks tight: our model gives a 42% chance of a price spike by "
        "6:30 PM (we act at 25%).",
        "It is 37 °C outside (we act at 35 °C).",
    ]
    # 60% of 39.2 kWh = 23.5 kWh = about 16 h at 1.5 kW.
    assert "23.5 kWh" in card.reserve and "16 h" in card.reserve and "usual 20%" in card.reserve

    # Different reasons give a different card; no reasons give no card at all.
    other = member_card(
        decide_reserve(StormSignals(outage_mw=31_000.0), BASE, CONFIG), EVENING, 39.2, CONFIG
    )
    assert other is not None and other.reasons == [
        "31,000 MW of Texas generation is out of service (we act at 20,000 MW)."
    ]
    calm = decide_reserve(StormSignals(p_spike=[0.0] * 16), BASE, CONFIG)
    assert member_card(calm, EVENING, 39.2, CONFIG) is None


def test_a_command_carrying_the_dynamic_floor_is_enforced_by_the_device():
    device = DeviceState(
        device_id="battery-0",
        soc_pct=0.65,
        energy_kwh=39.2,
        max_power_kw=10.0,
        round_trip_efficiency=0.9,
        reserve_floor_pct=BASE,
    )
    command = Command(
        idempotency_key="run:t:battery-0:1",
        run_id="run",
        interval_start=EVENING,
        device_id="battery-0",
        seq=1,
        setpoint_mw=0.01,
        expires_at=EVENING + timedelta(minutes=15),
        reserve_floor_pct=0.6,
    )
    after, ack = apply_command(device, command)
    # Only the 5% above the 60% floor may go: 1.96 kWh in 15 min = 7.84 kW, not 10 kW.
    assert ack.delivered_mw == pytest.approx(0.00784)
    assert after.soc_pct == pytest.approx(0.6) and after.reserve_floor_pct == 0.6
    assert not ack.floor_violation
    # Already at the floor: nothing to give.
    _, again = apply_command(after, command.model_copy(update={"idempotency_key": "k2"}))
    assert again.delivered_mw == 0.0


def evening_day() -> tuple[list[float], list[datetime], dict]:
    """A day whose evening (intervals 72-79) is priced high, with a Risk Curve that sees it
    coming from interval 64 on."""
    prices = [30.0] * 96
    for t in range(40, 48):
        prices[t] = 120.0  # an afternoon peak lp spends the fleet on
    for t in range(72, 80):
        prices[t] = 150.0
    starts = [
        datetime(2026, 1, 28, 6, 0, tzinfo=UTC) + timedelta(minutes=15 * t) for t in range(96)
    ]
    decisions = {}
    for t in range(96):
        p = [0.6 if 72 <= t + k < 80 else 0.0 for k in range(16)]
        decisions[t] = decide_reserve(StormSignals(p_spike=p), BASE, CONFIG)
    return prices, starts, decisions


def test_lp_storm_holds_the_dynamic_floor_and_equals_lp_on_a_calm_day():
    prices, _starts, decisions = evening_day()
    end_value = terminal_value(prices)
    lp = solve(prices, FLEET, LP, end_value)
    floors = {t: d.floor_by_interval_pct for t, d in decisions.items()}
    storm = lp_storm_schedule(prices, floors, FLEET, LP, end_value, lp)
    for t, energy in enumerate(storm.energy_mwh):
        floor = decisions[t].floor_pct * FLEET.capacity_mwh
        # Never discharged into the floor; a fleet caught below it when it rises charges.
        if storm.discharge_mw[t] > 0:
            assert energy >= floor - 1e-6, f"interval {t}: {energy:.3f} MWh below {floor:.3f}"
        # The lead gets it up to the floor before the tight evening (72-79).
        if 72 <= t < 80:
            assert energy >= floor - 1e-6, f"interval {t}: {energy:.3f} MWh below {floor:.3f}"
    assert all(storm.charge_mw[t] > 0 for t in range(64, 67))  # it rose, so charge up
    calm = {t: [BASE] * 16 for t in range(96)}
    assert lp_storm_schedule(prices, calm, FLEET, LP, end_value, lp) is lp


def test_tradeoff_numbers_are_the_backtests_values_and_schedules():
    prices, starts, decisions = evening_day()
    floors = {t: d.floor_by_interval_pct for t, d in decisions.items()}
    results, schedules = backtest_day_schedules(
        date(2026, 1, 28), prices, prices, "dam_spp", FLEET, LP, 90.0, 20.0, None, floors
    )
    row = storm_day(date(2026, 1, 28), starts, decisions, results, schedules, FLEET, 39.2, CONFIG)
    assert row is not None
    value = {r.strategy: r.value_usd for r in results}
    assert row.lp_value_usd == value["lp"]
    assert row.lp_storm_value_usd == value["lp_storm"]
    assert row.tradeoff.usd_forgone == value["lp"] - value["lp_storm"]
    assert row.tradeoff.usd_forgone >= 0  # a harder floor never earns more on the same plan

    raised = [decisions[t].raised for t in range(96)]
    assert row.raised_intervals == sum(raised) == 16  # 64..79
    assert row.first_raised_utc == starts[64]
    lp_soc = [s for s, r in zip(start_soc(schedules["lp"], FLEET), raised, strict=True) if r]
    storm_soc = [
        s for s, r in zip(start_soc(schedules["lp_storm"], FLEET), raised, strict=True) if r
    ]
    assert row.tradeoff.backup_hours_base == min(lp_soc) * 39.2 / 1.5
    assert row.tradeoff.backup_hours_storm == min(storm_soc) * 39.2 / 1.5
    assert row.tradeoff.backup_hours_gained > 0
    assert row.card is not None and row.card.headline.startswith("Why is your battery at 60%")
