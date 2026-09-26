"""`make insights`: value concentration and downtime cost from the cached RT prices.

Reads every cached rt_spp day for one Settlement Point, runs the pure analyses in
`insights/analysis.py` on the configured fleet, and writes the InsightsReport the Insights
tab reads (`data/cache/insights/insights.json`) plus the same numbers as CSV (and the
heatmap as SVG) for the README and the video. All derived from the cache, so never
committed.

uv run python -m gridtwin.insights.report [--settlement-point LZ_HOUSTON]
"""

import argparse
import csv
import logging
import time
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from gridtwin.insights.analysis import (
    Concentration,
    CurvePoint,
    DowntimeCell,
    Headline,
    TopDay,
    TopShare,
    concentration,
    downtime_cells,
    headline,
    hour_label,
    month_label,
    opportunities,
)
from gridtwin.marketdata import cache
from gridtwin.settings import settings

logger = logging.getLogger(__name__)

FORECAST_DATASETS = ("load_forecast_vintages", "load_actual")


class ForecastError(BaseModel, frozen=True):
    available: bool
    reason: str


class InsightsReport(BaseModel, frozen=True):
    settlement_point: str
    device_count: int
    fleet_mw: float
    start_day: date | None
    end_day: date | None
    headline: Headline | None
    concentration: list[Concentration]  # one per regime cached: post_rtcb (+ pre_rtcb)
    downtime: list[DowntimeCell]  # post_rtcb only
    forecast_error: ForecastError


def insights_dir() -> Path:
    return cache.cache_root() / "insights"


def report_path() -> Path:
    return insights_dir() / "insights.json"


def load_price_rows(settlement_point: str) -> list[tuple]:
    """(interval_start UTC, RT SPP, regime) for every cached real ERCOT interval."""
    if not cache.dataset_dir("rt_spp", "ALL").exists():
        return []
    rel = cache.dataset_view("rt_spp")
    return (
        rel.filter(f"settlement_point = '{settlement_point}' AND source != 'fixture_seed'")
        .project("interval_start_utc, price_usd_per_mwh, regime")
        .fetchall()
    )


def forecast_error_status() -> ForecastError:
    missing = [d for d in FORECAST_DATASETS if not cache.cached_days(d, "ALL")]
    if missing:
        return ForecastError(
            available=False,
            reason=(
                "needs ERCOT keys: net-load forecast history ("
                + ", ".join(missing)
                + ") is not cached. Set the ERCOT_API_* keys in .env and run `make data`."
            ),
        )
    return ForecastError(
        available=False,
        reason="forecast history is cached, but the forecast-error scatter is not built yet.",
    )


def build_report(rows: list[tuple], settlement_point: str) -> InsightsReport:
    fleet = settings.fleet_config()
    fleet_mw = fleet.device_count * fleet.max_power_kw / 1000.0
    opps = opportunities(rows, fleet_mw)
    regimes = sorted({o.regime for o in opps}, key=lambda r: r != "post_rtcb")
    conc = [concentration([o for o in opps if o.regime == r], r) for r in regimes]
    post = [o for o in opps if o.regime == "post_rtcb"]
    cells = downtime_cells(post)
    post_conc = next((c for c in conc if c.regime == "post_rtcb"), None)
    return InsightsReport(
        settlement_point=settlement_point,
        device_count=fleet.device_count,
        fleet_mw=fleet_mw,
        start_day=min((o.day for o in post), default=None),
        end_day=max((o.day for o in post), default=None),
        headline=headline(post_conc, cells) if post_conc and cells else None,
        concentration=conc,
        downtime=cells,
        forecast_error=forecast_error_status(),
    )


# CSV exports: one file per table, the same numbers the tab reads from insights.json.
CSV_FILES = {
    "top_intervals": "concentration_top_intervals.csv",
    "curve": "concentration_curve.csv",
    "top_days": "concentration_top_days.csv",
    "downtime": "downtime_heatmap.csv",
}


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def write_csvs(report: InsightsReport, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {k: out_dir / v for k, v in CSV_FILES.items()}
    _write_csv(
        paths["top_intervals"],
        ["regime", "top_pct", "intervals", "share_pct"],
        [
            [c.regime, t.top_pct, t.intervals, repr(t.share_pct)]
            for c in report.concentration
            for t in c.top_intervals
        ],
    )
    _write_csv(
        paths["curve"],
        ["regime", "intervals_pct", "value_pct"],
        [
            [c.regime, p.intervals_pct, repr(p.value_pct)]
            for c in report.concentration
            for p in c.curve
        ],
    )
    _write_csv(
        paths["top_days"],
        ["regime", "rank", "day", "opportunity_usd", "share_pct"],
        [
            [c.regime, i + 1, d.day.isoformat(), repr(d.opportunity_usd), repr(d.share_pct)]
            for c in report.concentration
            for i, d in enumerate(c.top_days)
        ],
    )
    _write_csv(
        paths["downtime"],
        ["month", "hour", "intervals", "mean_usd_per_min", "p95_usd_per_min"],
        [
            [c.month, c.hour, c.intervals, repr(c.mean_usd_per_min), repr(c.p95_usd_per_min)]
            for c in report.downtime
        ],
    )
    return list(paths.values())


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def read_csvs(out_dir: Path) -> dict:
    """The exported CSVs parsed back into the report's own models (regime-keyed)."""
    paths = {k: out_dir / v for k, v in CSV_FILES.items()}
    top_intervals: dict[str, list[TopShare]] = {}
    for r in _read_csv(paths["top_intervals"]):
        top_intervals.setdefault(r["regime"], []).append(
            TopShare(
                top_pct=float(r["top_pct"]),
                intervals=int(r["intervals"]),
                share_pct=float(r["share_pct"]),
            )
        )
    curve: dict[str, list[CurvePoint]] = {}
    for r in _read_csv(paths["curve"]):
        curve.setdefault(r["regime"], []).append(
            CurvePoint(intervals_pct=float(r["intervals_pct"]), value_pct=float(r["value_pct"]))
        )
    top_days: dict[str, list[TopDay]] = {}
    for r in _read_csv(paths["top_days"]):
        top_days.setdefault(r["regime"], []).append(
            TopDay(
                day=date.fromisoformat(r["day"]),
                opportunity_usd=float(r["opportunity_usd"]),
                share_pct=float(r["share_pct"]),
            )
        )
    downtime = [
        DowntimeCell(
            month=r["month"],
            hour=int(r["hour"]),
            intervals=int(r["intervals"]),
            mean_usd_per_min=float(r["mean_usd_per_min"]),
            p95_usd_per_min=float(r["p95_usd_per_min"]),
        )
        for r in _read_csv(paths["downtime"])
    ]
    return {
        "top_intervals": top_intervals,
        "curve": curve,
        "top_days": top_days,
        "downtime": downtime,
    }


def heatmap_svg(cells: list[DowntimeCell]) -> str:
    """The downtime-cost heatmap (mean $/min) as a standalone SVG, for the README."""
    months = sorted({c.month for c in cells})
    peak = max((c.mean_usd_per_min for c in cells), default=0.0) or 1.0
    cw, ch, left, top = 28, 22, 70, 30
    width, height = left + 24 * cw + 10, top + len(months) * ch + 30
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="sans-serif" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="#020617"/>',
        f'<text x="{left}" y="18" fill="#cbd5e1">Expected $ lost per minute of dispatch '
        f"outage (mean, $/min), hour of day (CT) x month; peak ${peak:,.0f}/min</text>",
    ]
    for i, month in enumerate(months):
        y = top + i * ch
        parts.append(
            f'<text x="{left - 6}" y="{y + 15}" fill="#94a3b8" text-anchor="end">'
            f"{month_label(month)}</text>"
        )
    for c in cells:
        x = left + c.hour * cw
        y = top + months.index(c.month) * ch
        alpha = min(1.0, c.mean_usd_per_min / peak)
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cw - 2}" height="{ch - 2}" '
            f'fill="#38bdf8" fill-opacity="{0.05 + 0.95 * alpha:.3f}"/>'
        )
    for hour in range(0, 24, 3):
        parts.append(
            f'<text x="{left + hour * cw}" y="{top + len(months) * ch + 14}" '
            f'fill="#94a3b8">{hour_label(hour)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def load_report() -> InsightsReport | None:
    path = report_path()
    if not path.exists():
        return None
    return InsightsReport.model_validate_json(path.read_text())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="gridtwin.insights.report")
    parser.add_argument("--settlement-point", default=settings.settlement_point)
    args = parser.parse_args()

    started = time.perf_counter()
    rows = load_price_rows(args.settlement_point)
    if not rows:
        raise SystemExit("no cached rt_spp days; run `make data` first")
    report = build_report(rows, args.settlement_point)
    out_dir = insights_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path().write_text(report.model_dump_json(indent=2))
    written = write_csvs(report, out_dir)
    svg = out_dir / "downtime_heatmap.svg"
    svg.write_text(heatmap_svg(report.downtime))

    print(
        f"{report.settlement_point} {report.start_day} -> {report.end_day}: "
        f"{report.device_count} devices, {report.fleet_mw:.1f} MW"
    )
    for c in report.concentration:
        tops = ", ".join(f"top {t.top_pct:g}% {t.share_pct:.1f}%" for t in c.top_intervals)
        print(
            f"{c.regime}: {c.intervals} intervals, {c.days} days, "
            f"${c.total_opportunity_usd:,.0f} opportunity; {tops}; "
            f"top {len(c.top_days)} days {c.top_days_share_pct:.1f}%"
        )
    if report.headline:
        print(report.headline.text)
    print(f"forecast error: {report.forecast_error.reason}")
    for path in [report_path(), *written, svg]:
        print(f"wrote {path}")
    print(f"took {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
    main()
