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

> **Local demos only.** The `chaos` service mounts `/var/run/docker.sock` so that it can
> kill and restart containers. That gives it root-equivalent control of the host's Docker
> daemon. Never run it anywhere except your own machine.

### Scripted scenarios

```
make chaos SCENARIO=worker-kill   # replays a scripted scenario, prints its Scenario Report
make chaos SCENARIO=duplicates    # duplicate + replayed batches: effects must stay 0
make test-e2e                     # the same scenarios as compose-mode tests with SLO asserts
```

Both need the stack running (`make up`). `make chaos` exits non-zero if any SLO is missed.
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
    apply: worker-kill            # the Chaos Scenario: worker-kill | duplicate-commands
    for_intervals: 2              # cleared (worker restarted) after n intervals of wall time
    target: worker-a              # optional; default the worker running the dispatch
```

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
