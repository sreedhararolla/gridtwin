"""Insights analyses on replayed RT prices: pure, no IO.

**Opportunity** of a Market Interval = fleet MW × max(0, RT SPP − that trading day's median
RT SPP) × 0.25 h: what the fleet could earn by discharging into that interval rather than
at a typical price that day. Everything here is derived from it:

- value concentration: the share of the window's Opportunity in the top 1% / 5% of
  intervals and the top 10 days;
- downtime cost: a minute of dispatch outage loses 1/15 of its interval's Opportunity, so
  $/min = fleet MW × max(0, RT SPP − day median) / 60, summarised per hour of day (Central
  time) × month as mean and p95.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

CENTRAL = ZoneInfo("America/Chicago")
INTERVAL_HOURS = 0.25
INTERVAL_MINUTES = 15
TOP_INTERVAL_PCTS = (1.0, 5.0)
TOP_DAYS = 10
# Points (share of intervals, %) on the concentration curve the Insights tab draws.
CURVE_PCTS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 50.0, 75.0, 100.0)
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class IntervalOpportunity(BaseModel, frozen=True):
    interval_start: datetime  # UTC
    day: date  # Central-time trading day
    hour: int  # hour of day, Central time
    month: str  # YYYY-MM, Central time
    regime: str
    price_usd_per_mwh: float
    day_median_usd_per_mwh: float
    opportunity_usd: float


class TopShare(BaseModel, frozen=True):
    top_pct: float
    intervals: int
    share_pct: float


class CurvePoint(BaseModel, frozen=True):
    intervals_pct: float
    value_pct: float


class TopDay(BaseModel, frozen=True):
    day: date
    opportunity_usd: float
    share_pct: float


class Concentration(BaseModel, frozen=True):
    regime: str
    intervals: int
    days: int
    total_opportunity_usd: float
    top_intervals: list[TopShare]
    top_days_share_pct: float
    top_days: list[TopDay]
    curve: list[CurvePoint]


class DowntimeCell(BaseModel, frozen=True):
    month: str  # YYYY-MM
    hour: int  # 0-23, Central time
    intervals: int
    mean_usd_per_min: float
    p95_usd_per_min: float


class Headline(BaseModel, frozen=True):
    top1_share_pct: float
    top5_share_pct: float
    top10_days_share_pct: float
    peak_month: str
    peak_hour: int
    peak_mean_usd_per_min: float
    peak_p95_usd_per_min: float
    text: str


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (numpy's default), for any non-empty list."""
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def opportunities(
    prices: Iterable[tuple[datetime, float, str]], fleet_mw: float
) -> list[IntervalOpportunity]:
    """(interval_start UTC, RT SPP, regime) rows -> one Opportunity per interval, sorted."""
    by_day: dict[date, list[tuple[datetime, float, str]]] = defaultdict(list)
    for start, price, regime in prices:
        by_day[start.astimezone(CENTRAL).date()].append((start, price, regime))
    out: list[IntervalOpportunity] = []
    for day in sorted(by_day):
        rows = sorted(by_day[day])
        median = statistics.median(price for _, price, _ in rows)
        for start, price, regime in rows:
            local = start.astimezone(CENTRAL)
            out.append(
                IntervalOpportunity(
                    interval_start=start,
                    day=day,
                    hour=local.hour,
                    month=f"{local.year:04d}-{local.month:02d}",
                    regime=regime,
                    price_usd_per_mwh=price,
                    day_median_usd_per_mwh=median,
                    opportunity_usd=fleet_mw * max(0.0, price - median) * INTERVAL_HOURS,
                )
            )
    return out


def _share(part: float, total: float) -> float:
    return 100.0 * part / total if total > 0 else 0.0


def _top_count(n: int, pct: float) -> int:
    return min(n, max(1, math.ceil(n * pct / 100.0)))


def concentration(rows: list[IntervalOpportunity], regime: str) -> Concentration:
    values = sorted((r.opportunity_usd for r in rows), reverse=True)
    total = sum(values)
    n = len(values)
    by_day: dict[date, float] = defaultdict(float)
    for r in rows:
        by_day[r.day] += r.opportunity_usd
    days = sorted(by_day.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_DAYS]
    return Concentration(
        regime=regime,
        intervals=n,
        days=len(by_day),
        total_opportunity_usd=total,
        top_intervals=[
            TopShare(
                top_pct=pct,
                intervals=_top_count(n, pct),
                share_pct=_share(sum(values[: _top_count(n, pct)]), total),
            )
            for pct in TOP_INTERVAL_PCTS
        ],
        top_days_share_pct=_share(sum(v for _, v in days), total),
        top_days=[TopDay(day=d, opportunity_usd=v, share_pct=_share(v, total)) for d, v in days],
        curve=[
            CurvePoint(
                intervals_pct=pct, value_pct=_share(sum(values[: _top_count(n, pct)]), total)
            )
            for pct in CURVE_PCTS
        ],
    )


def downtime_cells(rows: list[IntervalOpportunity]) -> list[DowntimeCell]:
    """Expected $ lost per minute of dispatch outage, per (month, hour of day)."""
    cells: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in rows:
        cells[(r.month, r.hour)].append(r.opportunity_usd / INTERVAL_MINUTES)
    return [
        DowntimeCell(
            month=month,
            hour=hour,
            intervals=len(per_min),
            mean_usd_per_min=statistics.fmean(per_min),
            p95_usd_per_min=percentile(per_min, 95.0),
        )
        for (month, hour), per_min in sorted(cells.items())
    ]


def hour_label(hour: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    return f"{(hour % 12) or 12} {suffix}"


def month_label(month: str) -> str:
    year, mon = month.split("-")
    return f"{MONTH_NAMES[int(mon) - 1]} {year}"


def headline(conc: Concentration, cells: list[DowntimeCell]) -> Headline:
    """The Insights headline, from the post-RTC+B concentration and the costliest cell."""
    shares = {t.top_pct: t.share_pct for t in conc.top_intervals}
    peak = max(cells, key=lambda c: (c.mean_usd_per_min, c.month, c.hour))
    text = (
        f"Top 1% of intervals hold {shares[1.0]:.0f}% of the value; a minute of downtime at "
        f"{hour_label(peak.hour)} in {month_label(peak.month)} costs "
        f"${peak.mean_usd_per_min:,.0f} on average (p95 ${peak.p95_usd_per_min:,.0f})."
    )
    return Headline(
        top1_share_pct=shares[1.0],
        top5_share_pct=shares[5.0],
        top10_days_share_pct=conc.top_days_share_pct,
        peak_month=peak.month,
        peak_hour=peak.hour,
        peak_mean_usd_per_min=peak.mean_usd_per_min,
        peak_p95_usd_per_min=peak.p95_usd_per_min,
        text=text,
    )
