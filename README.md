# GridTwin

A fault-tolerant VPP dispatch orchestrator. GridTwin replays real, post-RTC+B ERCOT
data to drive a simulated fleet of Base Power batteries on Temporal, and demonstrates
resilience under injected failures.

## Quickstart

```
make setup   # installs uv, Python 3.12, Node.js, gh and gets Docker running (no manual installs)
make up      # builds and starts every service
```

Then open:
- **Dashboard:** http://localhost:3000
- **Temporal UI:** http://localhost:8080

`make down` stops everything. `make logs` tails all service logs.

## What's running

`make up` starts Postgres, NATS, the Temporal dev server, the FastAPI backend, two
worker replicas, two fleet-simulator replicas (2,000 devices in 20 shards, 10 shards
each), the telemetry ingester and the Next.js dashboard. The dashboard's **Live** page
shows a green/red status dot per dependency and a `ready/total` count for workers and
simulators, polled every 2s.

## Replay any day

```
make data                     # cache real ERCOT RT prices (keyless; needs a US IP)
uv run python -m gridtwin.marketdata.cli demo-days   # rank cached days by spike
make demo DAY=2026-01-28      # replay one cached day at 60x with the full fleet
```

You can also pick a day on the **Live** page and press **Replay**. Each interval runs
20 shard dispatch activities at once; you can see them in the Temporal UI. The Live page
shows the fleet SoC band (p10/median/p90), how many devices are online, and each
interval's dispatch latency against its 15 s wall budget.

## Strategies and backtest

```
make train                            # scarcity-risk model: walk-forward CV, Risk Curves (~10 min)
make backtest                         # naive vs LP vs LP+risk vs perfect foresight
make demo DAY=2026-01-28              # then pick "lp" or "lp_risk" in the Live page's selector
uv run python -m gridtwin.replay.cli --day 2026-01-28 --strategy lp   # or from the CLI
```

- **`naive`** discharges fully at or above $90/MWh and charges at or below $20/MWh.
- **`lp`** is a rolling-horizon linear program (HiGHS via scipy) on the fleet aggregate. It
  plans 96 intervals ahead on the day-ahead (DAM SPP) price and acts on the first.
- **`perfect_foresight`** is the same LP on the actual RT prices. It is an upper bound
  and is not dispatchable.

The Insights page renders the backtest. Result at `LZ_HOUSTON`, 2025-12-05 → 2026-09-25
(295 days): 20 MW / 78.4 MWh fleet aggregate, each day from 50% SoC, $10/MWh degradation.

| Strategy | Value | $/MW-month | % of perfect foresight |
|---|---|---|---|
| naive | $231,106 | $1,192 | 31.1% |
| lp (DAM forecast) | $421,167 | $2,173 | 56.7% |
| lp_risk (DAM + Risk Curve) | $334,263 | $1,724 | 45.0% |
| perfect foresight | $742,738 | $3,832 | 100% |

Perfect foresight is ≥ every other Strategy on every one of the 295 days. A 96-interval
solve takes 17.5 ms p50 and 30.8 ms max, against a 200 ms budget.

**Honest caveats.**
- The LP beats naive in aggregate only because it plans on the DAM price. On a
  persistence forecast (yesterday's RT), which we tried before backfilling DAM, it *lost*
  to naive: $932 vs $1,250/MW-month. RT spikes are mostly not in yesterday's prices, and
  the LP spent energy on the wrong hours.
- Even with DAM, the LP captures only 57% of perfect foresight. RT scarcity spikes are
  largely not priced day-ahead. The scarcity-risk model (ticket 10, `docs/MODEL.md`)
  targets that gap. It ranks spike risk about 4x better than hour-of-day climatology
  (PR-AUC 0.178 vs 0.046, walk-forward). Its probabilities, though, beat climatology by
  only 5% (Brier skill). Trading on them through `lp_risk` currently *loses* money
  versus `lp`, so the Live tab uses it as a risk monitor. MODEL.md explains why.
- The backtest runs at fleet-aggregate level, without device noise or dropouts. Energy
  left at day end is valued at the day's median DAM price for every Strategy alike.
- See ADR-014 in `docs/DECISIONS.md`.

## Insights: what most people miss

```
make insights                         # from the cache in < 1 s; writes data/cache/insights/
```

The Insights page leads with the headline, which `make insights` computes from the cache:
**"Top 1% of intervals hold 28% of the value; a minute of downtime at 8 PM in Apr 2026
costs $20 on average (p95 $105)."** The numbers below are for `LZ_HOUSTON`, 2025-12-05 →
2026-09-25 (post-RTC+B, 28,316 intervals, 295 days) and the 2,000-Device, 20 MW fleet.

| Value concentration | Share of window value |
|---|---|
| Top 1% of intervals (284) | 28.2% |
| Top 5% of intervals (1,416) | 52.6% |
| Top 10 days (of 295) | 23.8% |

**Definitions.**
- **Opportunity** of a Market Interval = fleet MW × max(0, RT SPP − that Central-time
  trading day's median RT SPP) × 0.25 h, in $. It is what the fleet could earn by
  discharging into that interval rather than at a typical price that day.
- **Top N% share** = Opportunity in the ⌈N% × intervals⌉ highest-Opportunity intervals ÷
  the window's total Opportunity. **Top 10 days** = the same, summing Opportunity per day.
- **Downtime cost** ($/min) = Opportunity ÷ 15: a minute of dispatch outage loses 1/15 of
  its interval's Opportunity. The heatmap shows each hour of day (CT) × month as the mean
  and the p95 (linear interpolation) over that cell's intervals. The headline quotes the
  cell with the highest mean.

The same tables are exported as CSV (`concentration_top_intervals.csv`,
`concentration_curve.csv`, `concentration_top_days.csv`, `downtime_heatmap.csv`), and the
heatmap as `downtime_heatmap.svg`. A Seam B test checks that the CSVs match the report the
tab reads. Pre- vs post-RTC+B concentration appears automatically once pre-RTC+B days are
cached (`MARKETDATA_INCLUDE_PRE_RTCB=true`). The forecast-error-vs-price scatter needs
net-load forecast history, which requires the ERCOT API keys, so without them the tab says
"needs ERCOT keys". See ADR-016.

## Chaos

During a replay, press **Kill worker** in the Live page's chaos panel. The chaos
controller waits until one of the run's Shard dispatch activities is running, then
SIGKILLs the worker that is running it. The worker dot drops to 1/2, Temporal retries the
lost activities on the surviving worker, and no interval is skipped. The worker restarts
after `CHAOS_RESTART_DELAY_SECONDS` (20 s by default). The event timeline records each
chaos event's time, scenario and target. The SLO table compares target with actual for
within-tolerance %, reserve violations and **recovery time**: the time from the kill
until the interrupted interval's result is recorded. In the Temporal UI, open that
interval's workflow and look for a `dispatch_shard` activity whose started event shows
`attempt: 2` and `identity: worker-b` (or `worker-a`).

Press **Duplicate commands** to make every simulator deliver each Command batch twice and
sometimes replay an old batch. Devices dedupe by Idempotency Key, so the **Duplicate
deliveries** counter climbs while **Duplicate effects** stays at 0. The **Command Ledger**
panel shows any interval's Commands issued, acked, expired and failed; from a terminal,
`make ledger RUN=<run_id>` prints the same summary (omit `RUN` for the latest run).

Press **Partition 20 %** to take a seeded 20 % of Devices dark: their Commands and
Heartbeats drop. If an interval commands them before they go stale, they send no Ack; the
interval re-rates its Achievable Target without them and reallocates the Shortfall to
reachable Devices as `seq+1` Commands. One telemetry period later they are stale: the
**Online devices** readout drops (stale Devices greyed out) and the **Fleet timeline**
reads, for example, "400 devices stale" and "reallocated 1.59 MW to 1,600 devices". Press
**Telemetry delay 10 s** to make 30 % of Heartbeats arrive 10 s late: those Devices go
stale, so the Achievable Target is de-rated and nothing is planned on SoC that may be out
of date. `REALLOCATION_RESERVE_PCT` (10 %) of headroom is held back from the planner so a
Shortfall has somewhere to go (ADR-012).

> **Local demos only.** The `chaos` service mounts `/var/run/docker.sock` so that it can
> kill and restart containers. That gives it root-equivalent control of the host's Docker
> daemon. Never run it anywhere except your own machine.

### Scripted scenarios

```
make chaos SCENARIO=worker-kill   # replays a scripted scenario, prints its Scenario Report
make chaos SCENARIO=duplicates    # duplicate + replayed batches: effects must stay 0
make chaos SCENARIO=partition     # 20 % of devices dark: within tolerance of achievable
make chaos SCENARIO=telemetry-delay  # late heartbeats: stale, de-rated, 0 violations
make chaos SCENARIO=feed-outage   # feed raises: ladder L0 -> L1 -> L2, then back to L0
make chaos SCENARIO=feed-outlier  # $9,999 price: snapshot rejected, nothing dispatched on it
make test-e2e                     # the same scenarios as compose-mode tests with SLO asserts
```

All need the stack running (`make up`). `make chaos` exits non-zero if any SLO is missed.
Scenarios live in `scenarios/<name>.yaml`. The format is "at interval k, apply X for n
intervals" over a window of one replay day:

```yaml
name: worker-kill                 # used by make chaos SCENARIO=<name>
description: Kill a worker mid-dispatch at the spike peak.
settlement_point: LZ_HOUSTON      # optional; default SETTLEMENT_POINT
day: 2026-01-28                   # optional; a cached day. Omit it to use `fixture`
fixture: data/fixtures/rtm_spp_lz_houston_2026-01-28.csv   # optional; default FIXTURE_PATH
window:
  from_interval: 24               # index into the day's 15-min Market Intervals (0 = midnight CT)
  intervals: 24                   # optional; default to the end of the day
steps:
  - at_interval: 4                # index into the window
    apply: worker-kill            # worker-kill | duplicate-commands | partition | telemetry-delay
                                  # | feed-outage | feed-outlier
    for_intervals: 2              # cleared (worker restarted) after n intervals of wall time
    target: worker-a              # optional; default the worker running the dispatch
    pct: 0.2                      # partition / telemetry-delay: share of Devices hit
    delay_s: 10                   # telemetry-delay: how late Heartbeats arrive (wall s)
    at_offset_s: 12               # compose: wait this long into the interval before applying
```

`partition`, `telemetry-delay` and `duplicate-commands` scripts also run in-process, in
the Scenario Runner (`tests/test_scenario_partition.py`), where a step lands just after
the interval's telemetry is read: the worst case for a partition. So do `feed-outage` and
`feed-outlier` (`tests/test_scenario_feed.py`); a feed fault is on for the whole of each
interval it covers.

**Degradation Ladder.** When the feed fails or a snapshot is rejected, the Live tab's
badge steps from L0 Optimized to L1 Cached Plan (the last good plan, for 2 intervals),
then L2 Safe Rule (discharge only if the last valid price is at or above the threshold;
never charge), then L3 Hold (no Commands). After 3 failures the feed's circuit breaker
opens, and it probes the feed again 2 intervals later. After 2 clean intervals the ladder
is back at L0. The Live tab's **Break ERCOT feed** / **Restore ERCOT feed** and
**Inject $9,999** buttons drive this; tune it with `LADDER_*` and `FEED_*` in `.env`.

The runner starts the Replay Run and applies each step when the run reaches that
interval. When the run ends, it prints the Scenario Report, the chaos events, the retried
dispatch attempts from Temporal history, and the SLO table. The fleet seed and the
window are fixed, so the same script replays the same run.

If another stack already holds port 5432 or 3000, set `POSTGRES_HOST_PORT` and/or
`WEB_HOST_PORT` for `docker compose`, and point `CORS_ORIGINS` at the new web port.

## Development

- `make check` — ruff (format + lint), pytest, and the web app's lint/type-check/build.
- `make test` — the Python test suite without the compose-mode `e2e` tests.
- `make test-e2e` — compose-mode tests (needs `make up`).
- `make types` — regenerates the dashboard's TypeScript types from the API's OpenAPI
  schema (`web/src/types/api.ts`). Run this after any API model change; CI fails if it
  produces a diff that wasn't committed.

See `CONTEXT.md` for the project's domain language and `docs/SPEC.md` for the full spec.
