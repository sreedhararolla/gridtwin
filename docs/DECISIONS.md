# Decisions (ADR-lite)

Add one entry when a spec decision changes or a new test seam is introduced. Newest last.

## ADR-001: Temporal for orchestration
Base lists Temporal in its own stack. Durable execution gives us retries, timers, idempotent workflow ids and a visibility UI for the demo. **Fallback** if blocked by Friday midnight: Postgres-backed job queue plus advisory-lock leader election, keeping the same module boundaries.

## ADR-002: NATS for device transport
Lightweight, a single container, request/reply fits batched Commands with Acks, and partitions and delays are easy to inject. There is an in-memory implementation of the same interface for tests.

## ADR-003: Next.js dashboard with a typed API contract
Next.js (App Router) + React + TypeScript + Tailwind + Recharts, in its own container, talking directly to FastAPI (REST + SSE, with CORS for the dashboard origin).
- **Typed contract.** TypeScript types are generated from FastAPI's OpenAPI schema and checked in, so the Python/TypeScript contract can't drift silently.
- **SSE path.** The browser connects straight to FastAPI, not through Next.js rewrites, to avoid proxy buffering.
- **No network at runtime.** No runtime CDN; no Google Fonts via `next/font` (it downloads at build time). Use a local font or the system stack so the demo works on venue Wi-Fi.
- **Build early.** Build the web image in ticket 01 so `npm install` stays off the critical path.

## ADR-004: 15-minute settlement intervals
The market loop runs on 15-minute RT settlement intervals (NP6-905-CD). The 5-minute SCED LMPs are out of scope for the MVP.

## ADR-005: Two test seams
Seam A is the Scenario Report (system level). Seam B is the pure domain. No other seams without a new ADR.

## ADR-006: Trunk-based: commit straight to main
Tickets land as commits directly on `main`, with no PRs.
- **Gate.** A green local `make check` is required before every push. CI runs on each push, and a red `main` is fixed forward before anything else.
- **Closing.** The ticket's final commit carries `Closes #N`, which closes the issue when it lands on `main`.
- **Parallel sessions.** They use separate clones and `git pull --rebase` before pushing.

## ADR-007: Ticket 02's fixture is a placeholder, not a live ERCOT pull
Ticket 02 asks for "one real post-RTC+B day" of LZ_HOUSTON RT-SPP prices checked in as a fixture. The ERCOT Public API requires a subscription key (`ERCOT_API_*` in `.env`), which is optional per `CLAUDE.md` and was not supplied to this autopilot session, and ERCOT's public MIS pages do not expose an unauthenticated bulk-download endpoint for `NP6-905-CD`. Rather than park the ticket over an optional credential, `data/fixtures/rtm_spp_lz_houston_2025-12-10.csv` ships a deterministic, clearly-labeled placeholder: 96 x 15-minute intervals for `2025-12-10` (after the Dec 5, 2025 RTC+B go-live), same schema ERCOT publishes, with a realistic evening scarcity-style price shape ($11-$175/MWh). None of ticket 02's acceptance criteria require the fixture's *values* to be a live pull, only that the pipeline replays a fixture day end-to-end. Ticket 03 (ERCOT + weather data cache) owns the real ingest pipeline and replaces this file once keys are available.
