"""Scarcity-risk features, built only from what was known at decision time. Pure: no IO.

Every input is an `Obs`: the time it describes (`at`), the time it became known
(`known_at`) and its value. `build_features` refuses any input with `known_at` after the
decision time, so a caller that slices history wrongly fails loudly instead of leaking
the future into training or into a live Risk Curve.

Publication conventions (`*_known_at` below):
- RT SPP for a Market Interval is known when the interval ends.
- DAM SPP for a trading day is known at 13:30 Central the day before (DAM results post).
- An hourly temperature is known when its hour ends (Open-Meteo archive = observations).
"""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
INTERVAL = timedelta(minutes=15)
HORIZON_INTERVALS = 16  # the Risk Curve covers the next 4 hours
RT_LOOKBACK_INTERVALS = 96  # 24 h of RT history is all the builder needs
DAM_PUBLISHED_CT = time(13, 30)

FEATURE_NAMES = (
    "lead_intervals",
    "hour_ct",
    "day_of_week",
    "month",
    "dam_target",
    "dam_day_max",
    "dam_target_vs_day_max",
    "rt_last",
    "rt_max_4h",
    "rt_mean_24h",
    "rt_ramp_1h",
    "forecast_error_today",
    "temperature_c",
    "temperature_change_3h",
)


class Obs(NamedTuple):
    at: datetime  # the interval or hour the value describes (UTC)
    known_at: datetime  # when it was published (UTC)
    value: float


class LookaheadError(ValueError):
    """An input was timestamped after the decision time."""


@dataclass(frozen=True)
class KnownInputs:
    """What the builder may look at, each list sorted by `at`."""

    rt: list[Obs]  # RT SPP at the settlement point (the most recent ~24 h is enough)
    dam: list[Obs]  # DAM SPP hours around the decision (today, and tomorrow once published)
    temperature: list[Obs]  # hourly temperature (the most recent few hours)


def trading_day(ts: datetime) -> date:
    return ts.astimezone(CENTRAL).date()


def rt_known_at(interval_start: datetime) -> datetime:
    return interval_start + INTERVAL


def dam_known_at(day: date) -> datetime:
    published = datetime.combine(day - timedelta(days=1), DAM_PUBLISHED_CT, tzinfo=CENTRAL)
    return published.astimezone(UTC)


def temperature_known_at(hour_start: datetime) -> datetime:
    return hour_start + timedelta(hours=1)


def check_known(decision_time: datetime, inputs: KnownInputs) -> None:
    """The look-ahead guard: every input must have been published by `decision_time`."""
    for name, series in (
        ("rt", inputs.rt),
        ("dam", inputs.dam),
        ("temperature", inputs.temperature),
    ):
        for obs in series:
            if obs.known_at > decision_time:
                raise LookaheadError(
                    f"{name} for {obs.at.isoformat()} is known at {obs.known_at.isoformat()}, "
                    f"after the decision time {decision_time.isoformat()}"
                )


def targets_from(decision_time: datetime) -> list[datetime]:
    """The Market Intervals a Risk Curve made at `decision_time` covers: the one being
    decided and the next 15 (4 hours)."""
    return [decision_time + INTERVAL * k for k in range(HORIZON_INTERVALS)]


def _hour_start(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def build_features(decision_time: datetime, inputs: KnownInputs) -> list[list[float]]:
    """One feature row (in FEATURE_NAMES order) per target in `targets_from(decision_time)`.
    Missing values are NaN (LightGBM handles them)."""
    check_known(decision_time, inputs)
    nan = math.nan

    rt = [o.value for o in inputs.rt[-RT_LOOKBACK_INTERVALS:]]
    rt_last = rt[-1] if rt else nan
    rt_max_4h = max(rt[-16:]) if rt else nan
    rt_mean_24h = sum(rt) / len(rt) if rt else nan
    rt_ramp_1h = rt[-1] - rt[-5] if len(rt) >= 5 else nan

    dam_by_hour = {o.at: o.value for o in inputs.dam}
    dam_day_max: dict[date, float] = {}
    for o in inputs.dam:
        day = trading_day(o.at)
        dam_day_max[day] = max(dam_day_max.get(day, -math.inf), o.value)

    # Today's forecast error so far: RT minus the DAM for its hour, over today's intervals.
    today = trading_day(decision_time)
    errors = [
        o.value - dam_by_hour[_hour_start(o.at)]
        for o in inputs.rt
        if trading_day(o.at) == today and _hour_start(o.at) in dam_by_hour
    ]
    forecast_error_today = sum(errors) / len(errors) if errors else nan

    temps = [o.value for o in inputs.temperature]
    temperature = temps[-1] if temps else nan
    temperature_change_3h = temps[-1] - temps[-4] if len(temps) >= 4 else nan

    rows = []
    for lead, target in enumerate(targets_from(decision_time)):
        local = target.astimezone(CENTRAL)
        dam_target = dam_by_hour.get(_hour_start(target), nan)
        day_max = dam_day_max.get(local.date(), nan)
        ratio = dam_target / day_max if day_max and day_max > 0 else nan
        rows.append(
            [
                float(lead),
                local.hour + local.minute / 60.0,
                float(local.weekday()),
                float(local.month),
                dam_target,
                day_max,
                ratio,
                rt_last,
                rt_max_4h,
                rt_mean_24h,
                rt_ramp_1h,
                forecast_error_today,
                temperature,
                temperature_change_3h,
            ]
        )
    return rows


def spike_threshold(prices: list[float], quantile: float = 0.99) -> float:
    """The label threshold: the `quantile` of RT prices in the training window."""
    if not prices:
        raise ValueError("no prices to compute a spike threshold from")
    ordered = sorted(prices)
    pos = quantile * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
