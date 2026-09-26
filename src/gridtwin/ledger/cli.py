"""`make ledger [RUN=<run_id>]`: print the Command Ledger summary per Market Interval
(issued / acked / expired / failed) and the run's duplicate counters, from Postgres."""

import argparse
import sys

from gridtwin.ledger.postgres_repo import PostgresLedgerRepo


def main() -> int:
    parser = argparse.ArgumentParser(prog="gridtwin.ledger")
    parser.add_argument("run_id", nargs="?", help="default: the latest Replay Run")
    args = parser.parse_args()

    repo = PostgresLedgerRepo()
    run_id = args.run_id or repo.latest_run_id()
    if run_id is None:
        print("no Replay Run in the ledger yet", file=sys.stderr)
        return 1

    results = {r.interval_start: r for r in repo.list_interval_results(run_id)}
    print(f"Command Ledger: run {run_id}")
    print(
        f"  {'interval (UTC)':<26}{'issued':>7}{'acked':>7}{'expired':>8}{'failed':>7}"
        f"{'unacked':>8}{'delivered MW':>14}{'dup deliv':>10}{'dup eff':>8}"
    )
    for s in repo.ledger_summary(run_id):
        r = results.get(s.interval_start)
        print(
            f"  {s.interval_start.isoformat():<26}{s.issued:>7}{s.acked:>7}{s.expired:>8}"
            f"{s.failed:>7}{s.unacked:>8}{s.delivered_mw:>14.3f}"
            f"{r.duplicate_deliveries if r else 0:>10}{r.duplicate_effects if r else 0:>8}"
        )
    all_results = list(results.values())
    print(
        f"\nTotal: duplicate deliveries {sum(r.duplicate_deliveries for r in all_results)}, "
        f"duplicate effects {sum(r.duplicate_effects for r in all_results)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
