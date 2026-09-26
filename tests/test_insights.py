"""Seam B: the Insights analyses (value concentration, downtime cost, headline) and their
CSV exports, on the two checked-in fixture days."""

import math
import statistics
from datetime import UTC, datetime, timedelta

import pytest

from gridtwin.insights import analysis, report
from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.settings import settings

FIXTURES = (
    "data/fixtures/rtm_spp_lz_houston_2025-12-10.csv",
    "data/fixtures/rtm_spp_lz_houston_2026-01-28.csv",
)
FLEET_MW = 20.0


def fixture_rows() -> list[tuple[datetime, float, str]]:
    return [
        (start, price, "post_rtcb")
        for path in FIXTURES
        for start, price in load_fixture_day("LZ_HOUSTON", path)
    ]


def test_opportunity_is_fleet_mw_times_excess_over_day_median() -> None:
    rows = fixture_rows()
    opps = analysis.opportunities(rows, FLEET_MW)
    assert len(opps) == len(rows) == 192
    for path in FIXTURES:
        day = load_fixture_day("LZ_HOUSTON", path)
        median = statistics.median(p for _, p in day)
        by_start = {o.interval_start: o for o in opps}
        for start, price in day:
            assert by_start[start].opportunity_usd == pytest.approx(
                FLEET_MW * max(0.0, price - median) * 0.25
            )


def test_headline_is_computed_from_the_fixture_not_hardcoded() -> None:
    opps = analysis.opportunities(fixture_rows(), FLEET_MW)
    conc = analysis.concentration(opps, "post_rtcb")
    cells = analysis.downtime_cells(opps)
    head = analysis.headline(conc, cells)

    # Independent brute force: top ceil(1% of 192) = 2 intervals.
    values = sorted((o.opportunity_usd for o in opps), reverse=True)
    total = sum(values)
    assert head.top1_share_pct == pytest.approx(100 * sum(values[:2]) / total)
    assert head.top5_share_pct == pytest.approx(100 * sum(values[: math.ceil(192 * 0.05)]) / total)
    assert head.top10_days_share_pct == pytest.approx(100.0)  # only two days

    per_cell: dict[tuple[str, int], list[float]] = {}
    for o in opps:
        local = o.interval_start.astimezone(analysis.CENTRAL)
        key = (f"{local.year:04d}-{local.month:02d}", local.hour)
        per_cell.setdefault(key, []).append(o.opportunity_usd / 15)
    (month, hour), worst = max(per_cell.items(), key=lambda kv: statistics.fmean(kv[1]))
    assert (head.peak_month, head.peak_hour) == (month, hour)
    assert head.peak_mean_usd_per_min == pytest.approx(statistics.fmean(worst))
    assert f"{head.top1_share_pct:.0f}%" in head.text
    assert f"${head.peak_mean_usd_per_min:,.0f}" in head.text

    # Move one price and the headline moves with it.
    bumped = [
        (s, p + (5000.0 if i == 10 else 0.0), r) for i, (s, p, r) in enumerate(fixture_rows())
    ]
    opps2 = analysis.opportunities(bumped, FLEET_MW)
    head2 = analysis.headline(
        analysis.concentration(opps2, "post_rtcb"), analysis.downtime_cells(opps2)
    )
    assert head2.top1_share_pct > head.top1_share_pct
    assert head2.text != head.text


def test_one_spike_holds_all_the_value() -> None:
    start = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)  # 00:00 CDT
    rows = [(start + timedelta(minutes=15 * i), 25.0, "post_rtcb") for i in range(96)]
    rows[76] = (rows[76][0], 1025.0, "post_rtcb")  # 19:00 CDT
    opps = analysis.opportunities(rows, FLEET_MW)
    conc = analysis.concentration(opps, "post_rtcb")
    assert conc.total_opportunity_usd == pytest.approx(FLEET_MW * 1000 * 0.25)
    assert [t.share_pct for t in conc.top_intervals] == [pytest.approx(100.0)] * 2
    head = analysis.headline(conc, analysis.downtime_cells(opps))
    assert (head.peak_month, head.peak_hour) == ("2026-08", 19)
    # 4 intervals start in the 7 PM hour; one holds $5,000 -> $333/min, mean over 4.
    assert head.peak_mean_usd_per_min == pytest.approx(5000 / 15 / 4)
    assert "7 PM in Aug 2026" in head.text


def test_percentile_matches_linear_interpolation() -> None:
    assert analysis.percentile([5.0], 95) == 5.0
    assert analysis.percentile([0.0, 10.0], 95) == pytest.approx(9.5)
    assert analysis.percentile(list(map(float, range(101))), 95) == pytest.approx(95.0)


def test_exported_csvs_match_the_report_the_tab_reads(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "marketdata_cache_dir", str(tmp_path / "cache"))
    built = report.build_report(fixture_rows(), "LZ_HOUSTON")
    # The tab reads insights.json; round-trip it the way the API does.
    served = report.InsightsReport.model_validate_json(built.model_dump_json())
    report.write_csvs(built, tmp_path)
    exported = report.read_csvs(tmp_path)

    (post,) = served.concentration
    assert exported["top_intervals"]["post_rtcb"] == post.top_intervals
    assert exported["curve"]["post_rtcb"] == post.curve
    assert exported["top_days"]["post_rtcb"] == post.top_days
    assert exported["downtime"] == served.downtime
    assert served.headline is not None
    assert served.headline.top1_share_pct == post.top_intervals[0].share_pct
    assert not served.forecast_error.available
    assert "needs ERCOT keys" in served.forecast_error.reason
