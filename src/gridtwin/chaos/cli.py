"""`make chaos SCENARIO=<name>`: run scenarios/<name>.yaml against the compose stack and
print its Scenario Report and SLO table. Exits non-zero if any SLO is missed."""

import argparse
import asyncio
import logging
import sys

from gridtwin.chaos.runner import load_script, run_chaos_script

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # the runner polls; keep the log readable
log = logging.getLogger("chaos")


async def main() -> int:
    parser = argparse.ArgumentParser(prog="gridtwin.chaos")
    parser.add_argument("scenario", help="a script in scenarios/, without .yaml")
    args = parser.parse_args()

    script = load_script(args.scenario)
    log.info("scenario %s: %s", script.name, script.description)
    outcome = await run_chaos_script(script)

    print(f"\nScenario Report: {script.name} (run {outcome.run_id})")
    print(outcome.report.model_dump_json(indent=2))
    print("\nChaos events:")
    for e in outcome.events:
        where = f" interval {e.interval_start.isoformat()}" if e.interval_start else ""
        print(f"  {e.at.isoformat()}  {e.scenario} {e.action} {e.target}{where}  {e.detail}")
    print("\nTemporal history, retried dispatch attempts:")
    for a in outcome.retries:
        status = "completed" if a.completed else "not completed"
        print(f"  {a.activity_id} attempt {a.attempt} on {a.worker}: {status}")
    print("\nSLO                  target            actual")
    for row in outcome.slo:
        mark = "PASS" if row.ok else "FAIL"
        print(f"  {row.name:<19}{row.target:<18}{row.actual:<16}{mark}")
    for r in outcome.retries[:1]:
        print(f"\nTemporal UI: http://localhost:8080/namespaces/default/workflows/{r.workflow_id}")
    return 0 if outcome.slos_met else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
