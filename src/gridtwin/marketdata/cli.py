"""`make data` and friends: ingest, audit, demo-days, one-time fixture seed.

uv run python -m gridtwin.marketdata.cli ingest
uv run python -m gridtwin.marketdata.cli audit
uv run python -m gridtwin.marketdata.cli demo-days
uv run python -m gridtwin.marketdata.cli seed-fixture-day
"""

import argparse
import logging
from datetime import date

from gridtwin.marketdata.audit import build_audit, format_audit
from gridtwin.marketdata.demo_days import rank_cached_days
from gridtwin.marketdata.fixture_seed import seed_fixture_day
from gridtwin.marketdata.ingest import default_window, run_ingest
from gridtwin.marketdata.registry import default_registry
from gridtwin.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _add_window_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--include-pre-rtcb", action="store_true", default=settings.marketdata_include_pre_rtcb
    )


def cmd_ingest(args: argparse.Namespace) -> None:
    default_start, default_end = default_window()
    start = args.start or default_start
    end = args.end or default_end
    summary = run_ingest(default_registry(), start, end, include_pre_rtcb=args.include_pre_rtcb)
    print(
        f"fetched={summary.fetched} skipped_cached={summary.skipped_cached} "
        f"pending_credentials={summary.skipped_pending_credentials} errors={summary.errors}"
    )


def cmd_audit(args: argparse.Namespace) -> None:
    default_start, default_end = default_window()
    start = args.start or default_start
    end = args.end or default_end
    rows = build_audit(default_registry(), start, end, include_pre_rtcb=args.include_pre_rtcb)
    print(format_audit(rows))


def cmd_demo_days(args: argparse.Namespace) -> None:
    by_max, by_spread = rank_cached_days(settlement_point=args.settlement_point, top_n=args.top_n)
    print(f"Top {args.top_n} days by max RT price at {args.settlement_point}:")
    for stat in by_max:
        print(f"  {stat.day}  max=${stat.max_price_usd_per_mwh:.2f}/MWh")
    print(f"Top {args.top_n} days by intraday spread at {args.settlement_point}:")
    for stat in by_spread:
        print(f"  {stat.day}  spread=${stat.spread_usd_per_mwh:.2f}/MWh")


def cmd_seed_fixture_day(_args: argparse.Namespace) -> None:
    seed_fixture_day()
    print("seeded the ADR-007 fixture day into the rt_spp cache (source=fixture_seed)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="gridtwin.marketdata")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest")
    _add_window_args(ingest_parser)
    ingest_parser.set_defaults(func=cmd_ingest)

    audit_parser = subparsers.add_parser("audit")
    _add_window_args(audit_parser)
    audit_parser.set_defaults(func=cmd_audit)

    demo_days_parser = subparsers.add_parser("demo-days")
    demo_days_parser.add_argument("--settlement-point", default=settings.settlement_point)
    demo_days_parser.add_argument("--top-n", type=int, default=10)
    demo_days_parser.set_defaults(func=cmd_demo_days)

    seed_parser = subparsers.add_parser("seed-fixture-day")
    seed_parser.set_defaults(func=cmd_seed_fixture_day)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
