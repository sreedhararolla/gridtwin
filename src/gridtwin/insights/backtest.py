"""`make backtest`: naive vs LP vs LP + Risk Curve vs perfect foresight over every cached
post-RTC+B day, on the fleet aggregate, each day from the same starting SoC. `lp_risk`
uses the out-of-sample Risk Curves `make train` stored (without them it plans as `lp`,
re-planned hourly). Writes a BacktestReport to
`data/cache/insights/backtest.json` (derived from the cache, so never committed).

uv run python -m gridtwin.insights.backtest [--settlement-point LZ_HOUSTON]
"""

import argparse
import logging
import statistics
import time
from pathlib import Path

from gridtwin.marketdata import cache
from gridtwin.marketdata.forecast import forecast_prices
from gridtwin.marketdata.prices import load_day_prices
from gridtwin.planner.backtest import (
    BacktestReport,
    DayResult,
    backtest_day,
    fit_forecast,
    summarize,
)
from gridtwin.planner.lp import FleetAggregate, LpConfig, solve, terminal_value
from gridtwin.risk.store import risk_curve
from gridtwin.settings import settings

logger = logging.getLogger(__name__)


def report_path() -> Path:
    return cache.cache_root() / "insights" / "backtest.json"


def fleet_aggregate() -> FleetAggregate:
    fleet = settings.fleet_config()
    capacity = fleet.device_count * fleet.energy_kwh / 1000.0
    power = fleet.device_count * fleet.max_power_kw / 1000.0
    return FleetAggregate(
        max_discharge_mw=power,
        max_charge_mw=power,
        capacity_mwh=capacity,
        floor_mwh=capacity * fleet.reserve_floor_pct,
        energy_mwh=capacity * fleet.initial_soc_pct,
        round_trip_efficiency=fleet.round_trip_efficiency,
    )


def time_solves(prices: list[list[float]], fleet: FleetAggregate, config: LpConfig) -> list[float]:
    """Wall ms per 96-interval solve (the live rolling horizon's size)."""
    timings = []
    for day_prices in prices:
        horizon = fit_forecast(day_prices, config.horizon_intervals)
        started = time.perf_counter()
        solve(horizon, fleet, config, terminal_value(horizon))
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def run_backtest(settlement_point: str) -> BacktestReport:
    fleet = fleet_aggregate()
    config = settings.lp_config()
    days = sorted(d for d in cache.cached_days("rt_spp", "ALL") if d >= cache.RTCB_GO_LIVE)
    results: list[DayResult] = []
    actuals: list[list[float]] = []
    for day in days:
        rows = load_day_prices(settlement_point, day, settings.fixture_path)
        if not rows:
            continue
        starts = [start for start, _ in rows]
        actual = [price for _, price in rows]
        forecast, source = forecast_prices(settlement_point, starts, settings.fixture_path)
        if source == "none":
            logger.info("skip %s: no forecast (no DAM and no previous RT day)", day)
            continue
        risk = {}
        for t, start in enumerate(starts):
            curve = risk_curve(settlement_point, start)
            if curve is not None:
                risk[t] = (curve.p_spike, curve.spike_premium_usd_per_mwh)
        actuals.append(actual)
        results.extend(
            backtest_day(
                day,
                actual,
                forecast,
                source,
                fleet,
                config,
                settings.naive_discharge_threshold_usd,
                settings.naive_charge_threshold_usd,
                risk,
            )
        )
    timings = time_solves(actuals, fleet, config)
    return BacktestReport(
        settlement_point=settlement_point,
        start_day=min((r.day for r in results), default=None),
        end_day=max((r.day for r in results), default=None),
        fleet_mw=fleet.max_discharge_mw,
        fleet_mwh=fleet.capacity_mwh,
        start_soc_pct=100.0 * fleet.energy_mwh / fleet.capacity_mwh,
        degradation_usd_per_mwh=config.degradation_usd_per_mwh,
        naive_discharge_threshold_usd=settings.naive_discharge_threshold_usd,
        naive_charge_threshold_usd=settings.naive_charge_threshold_usd,
        lp_solve_ms_p50=statistics.median(timings) if timings else 0.0,
        lp_solve_ms_max=max(timings, default=0.0),
        summary=summarize(results, fleet.max_discharge_mw),
        days=results,
    )


def load_report() -> BacktestReport | None:
    path = report_path()
    if not path.exists():
        return None
    return BacktestReport.model_validate_json(path.read_text())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="gridtwin.insights.backtest")
    parser.add_argument("--settlement-point", default=settings.settlement_point)
    args = parser.parse_args()

    report = run_backtest(args.settlement_point)
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))

    print(
        f"{args.settlement_point} {report.start_day} -> {report.end_day}: "
        f"{report.fleet_mw:.1f} MW / {report.fleet_mwh:.1f} MWh fleet"
    )
    print(f"{'strategy':<18} {'days':>5} {'value $':>12} {'$/MW-month':>11} {'% of PF':>8}")
    for s in report.summary:
        print(
            f"{s.strategy:<18} {s.days:>5} {s.value_usd:>12,.0f} {s.usd_per_mw_month:>11,.0f} "
            f"{s.share_of_perfect_foresight_pct:>7.1f}%"
        )
    by_day: dict = {}
    for r in report.days:
        by_day.setdefault(r.day, {})[r.strategy] = r.value_usd
    violations = [
        d for d, v in by_day.items() if any(v["perfect_foresight"] < x - 0.01 for x in v.values())
    ]
    print(f"days where perfect foresight < another strategy: {len(violations)}")
    print(
        f"96-interval LP solve: p50 {report.lp_solve_ms_p50:.1f} ms, "
        f"max {report.lp_solve_ms_max:.1f} ms"
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
