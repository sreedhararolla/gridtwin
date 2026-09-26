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
worker replicas, two fleet-simulator replicas and the Next.js dashboard. The
dashboard's **Live** page shows a green/red status dot per dependency and a
`ready/total` count for workers and simulators, polled every 2s.

## Development

- `make check` — ruff (format + lint), pytest, and the web app's lint/type-check/build.
- `make test` — just the Python test suite.
- `make types` — regenerates the dashboard's TypeScript types from the API's OpenAPI
  schema (`web/src/types/api.ts`). Run this after any API model change; CI fails if it
  produces a diff that wasn't committed.

See `CONTEXT.md` for the project's domain language and `docs/SPEC.md` for the full spec.
