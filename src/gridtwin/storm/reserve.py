"""Storm mode (ticket 14): the Dynamic Reserve Floor, the Reserve Reasons behind it, the
Member Card that explains it and the Storm Trade-off. Pure: no IO (the signals are read in
storm/signals.py), and deterministic, so the dispatch workflow may call it.

The floor rises from the base Reserve Floor to the storm floor when a signal crosses its
threshold: grid tightness (the Risk Curve's spike probability, or outage capacity) or
severe weather (temperature). A tight interval raises the floor `lead_intervals` ahead of
it, so the fleet has time to charge up to the storm floor before the evening arrives.
"""

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

CENTRAL = ZoneInfo("America/Chicago")
INTERVAL = timedelta(minutes=15)


class StormConfig(BaseModel, frozen=True):
    enabled: bool = False
    storm_floor_pct: float = 0.60  # the Reserve Floor while any Reserve Reason holds
    risk_threshold: float = 0.25  # p(spike) at which an interval counts as grid-tight
    outage_threshold_mw: float = 20_000.0  # ERCOT outage capacity
    heat_threshold_c: float = 35.0
    cold_threshold_c: float = -5.0
    lead_intervals: int = 8  # raise the floor this far ahead of a tight interval (2 h)
    home_backup_load_kw: float = 1.5  # a home's essential load, for backup hours


class StormSignals(BaseModel, frozen=True):
    """What the grid and the weather look like at decision time. None = not available."""

    p_spike: list[float] = []  # the Risk Curve made now (this interval first)
    outage_mw: float | None = None
    temperature_c: float | None = None  # the latest observed hour


ReasonKind = Literal["grid_tight", "outages", "heat", "cold"]


class ReserveReason(BaseModel, frozen=True):
    """One signal over its threshold: the structured input to the Member Card."""

    kind: ReasonKind
    value: float  # p(spike) 0-1, MW on outage, or °C
    threshold: float
    lead_intervals: int = 0  # grid_tight: intervals until the first tight interval


class ReserveDecision(BaseModel, frozen=True):
    floor_pct: float  # this interval's Reserve Floor, 0-1
    base_floor_pct: float
    reasons: list[ReserveReason] = []
    # The floor for each upcoming interval the Risk Curve covers (this one first), so the
    # planner can charge ahead of a floor that rises later.
    floor_by_interval_pct: list[float] = []

    @property
    def raised(self) -> bool:
        return self.floor_pct > self.base_floor_pct


def decide_reserve(
    signals: StormSignals, base_floor_pct: float, config: StormConfig
) -> ReserveDecision:
    """The Dynamic Reserve Floor for this interval and the ones the Risk Curve covers."""
    if not config.enabled:
        return ReserveDecision(
            floor_pct=base_floor_pct,
            base_floor_pct=base_floor_pct,
            floor_by_interval_pct=[base_floor_pct],
        )
    storm = max(config.storm_floor_pct, base_floor_pct)
    # Outages and weather are known now and hold for the whole horizon.
    standing: list[ReserveReason] = []
    if signals.outage_mw is not None and signals.outage_mw >= config.outage_threshold_mw:
        standing.append(
            ReserveReason(
                kind="outages", value=signals.outage_mw, threshold=config.outage_threshold_mw
            )
        )
    temp = signals.temperature_c
    if temp is not None and temp >= config.heat_threshold_c:
        standing.append(ReserveReason(kind="heat", value=temp, threshold=config.heat_threshold_c))
    if temp is not None and temp <= config.cold_threshold_c:
        standing.append(ReserveReason(kind="cold", value=temp, threshold=config.cold_threshold_c))

    tight = [t for t, p in enumerate(signals.p_spike) if p >= config.risk_threshold]
    lead = config.lead_intervals
    floors = [
        storm if standing or any(t <= k <= t + lead for k in tight) else base_floor_pct
        for t in range(max(len(signals.p_spike), 1))
    ]
    reasons: list[ReserveReason] = []
    first_tight = next((k for k in tight if k <= lead), None)
    if first_tight is not None:
        reasons.append(
            ReserveReason(
                kind="grid_tight",
                value=max(signals.p_spike[: lead + 1]),
                threshold=config.risk_threshold,
                lead_intervals=first_tight,
            )
        )
    reasons.extend(standing)
    return ReserveDecision(
        floor_pct=storm if reasons else base_floor_pct,
        base_floor_pct=base_floor_pct,
        reasons=reasons,
        floor_by_interval_pct=floors,
    )


class MemberCard(BaseModel, frozen=True):
    """'Why is your battery at 60% tonight?': every sentence comes from a Reserve Reason
    or the decision's numbers (a template, no LLM)."""

    headline: str
    reasons: list[str]
    reserve: str


def _clock(ts: datetime) -> str:
    local = ts.astimezone(CENTRAL)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def _part_of_day(ts: datetime) -> str:
    hour = ts.astimezone(CENTRAL).hour
    if hour >= 17 or hour < 4:
        return "tonight"
    return "this morning" if hour < 12 else "this afternoon"


def _reason_text(reason: ReserveReason, decision_time: datetime) -> str:
    if reason.kind == "grid_tight":
        when = (
            "right now"
            if reason.lead_intervals == 0
            else f"by {_clock(decision_time + INTERVAL * reason.lead_intervals)}"
        )
        return (
            f"ERCOT's grid looks tight: our model gives a {reason.value:.0%} chance of a "
            f"price spike {when} (we act at {reason.threshold:.0%})."
        )
    if reason.kind == "outages":
        return (
            f"{reason.value:,.0f} MW of Texas generation is out of service "
            f"(we act at {reason.threshold:,.0f} MW)."
        )
    if reason.kind == "heat":
        return f"It is {reason.value:.0f} °C outside (we act at {reason.threshold:.0f} °C)."
    return f"It is {reason.value:.0f} °C outside (we act at {reason.threshold:.0f} °C or colder)."


def member_card(
    decision: ReserveDecision,
    decision_time: datetime,
    device_energy_kwh: float,
    config: StormConfig,
) -> MemberCard | None:
    """The card a Member sees while the floor is raised; None when it is not."""
    if not decision.raised or not decision.reasons:
        return None
    lead = next((r.lead_intervals for r in decision.reasons if r.kind == "grid_tight"), 0)
    pct = decision.floor_pct * 100
    reserve_kwh = decision.floor_pct * device_energy_kwh
    hours = reserve_kwh / config.home_backup_load_kw
    when = _part_of_day(decision_time + INTERVAL * lead)
    return MemberCard(
        headline=f"Why is your battery at {pct:.0f}% {when}?",
        reasons=[_reason_text(r, decision_time) for r in decision.reasons],
        reserve=(
            f"We are keeping {pct:.0f}% ({reserve_kwh:.1f} kWh, about {hours:.0f} h of backup "
            f"at {config.home_backup_load_kw:g} kW) for you instead of the usual "
            f"{decision.base_floor_pct * 100:.0f}%. It goes back to "
            f"{decision.base_floor_pct * 100:.0f}% once conditions ease."
        ),
    )


class StormTradeoff(BaseModel, frozen=True):
    """$ forgone vs backup hours gained, from the same backtest schedules."""

    usd_forgone: float  # lp value - lp_storm value
    backup_hours_base: float  # lowest per-home backup across the raised intervals, lp
    backup_hours_storm: float  # the same under lp_storm
    backup_hours_gained: float


def backup_hours(
    soc_pct: list[float], raised: list[bool], device_energy_kwh: float, load_kw: float
) -> float:
    """The least backup a home had at the start of any raised interval (hours at `load_kw`)."""
    held = [soc for soc, r in zip(soc_pct, raised, strict=True) if r]
    return min(held, default=0.0) * device_energy_kwh / load_kw


def storm_tradeoff(
    lp_value_usd: float,
    storm_value_usd: float,
    lp_soc_pct: list[float],
    storm_soc_pct: list[float],
    raised: list[bool],
    device_energy_kwh: float,
    config: StormConfig,
) -> StormTradeoff:
    """`*_soc_pct` is the fleet SoC (0-1) at the start of each interval of the day."""
    base = backup_hours(lp_soc_pct, raised, device_energy_kwh, config.home_backup_load_kw)
    storm = backup_hours(storm_soc_pct, raised, device_energy_kwh, config.home_backup_load_kw)
    return StormTradeoff(
        usd_forgone=lp_value_usd - storm_value_usd,
        backup_hours_base=base,
        backup_hours_storm=storm,
        backup_hours_gained=storm - base,
    )


class StormDay(BaseModel, frozen=True):
    """One backtest day on which Storm mode raised the Reserve Floor: the trade-off panel's
    row and the Member Card from the first raised interval."""

    day: date
    raised_intervals: int
    first_raised_utc: datetime
    base_floor_pct: float  # 0-100
    max_floor_pct: float  # 0-100
    lp_value_usd: float
    lp_storm_value_usd: float
    tradeoff: StormTradeoff
    reasons: list[ReserveReason]
    card: MemberCard | None
