# 01: Walking skeleton

**Type:** AFK · **Priority:** P0 · **Blocked by:** none · **User stories:** 12, 18

## What to build
A runnable skeleton with every long-lived dependency wired and visible, so that later tickets only add behaviour. It includes:
- A Python project managed with `uv`.
- Containers for Postgres, NATS, the Temporal dev server (pinned tag), the API/dashboard, **two** worker replicas and **two** fleet-simulator replicas. Workers and simulators are stubs that connect and report liveness.
- A health endpoint that aggregates dependency status.
- The dashboard shell: a **Next.js (App Router, TypeScript, Tailwind)** app in its own container with a shared layout and the pages *Live*, *Data* and *Insights* (empty for now). The Live page shows a status dot per dependency.
- A typed API contract: FastAPI's OpenAPI schema generates the dashboard's TypeScript types (`make types`). The generated file is checked in.
- Makefile targets `setup` (runs `scripts/bootstrap.sh`), `up`, `down`, `logs`, `check`, `test`, `types`.
- A CI workflow running `make check` on every push to `main`.
- `.env.example`; `.gitignore` covering `.env` and the data cache.

Tracer bullet first: get **one** dependency (Postgres) green end-to-end through the health endpoint and the dot on the page. Then add the rest.

## Demo path
`make up` → open the dashboard → green dots for Postgres, NATS, Temporal, workers (2/2) and simulators (2/2). `docker stop` one worker → its dot shows 1/2 within 5 s.

## Acceptance criteria
- [ ] From a clean clone, `make up` starts all services and `make down` stops them.
- [ ] The health endpoint returns per-dependency JSON and a non-200 status when any core dependency is down.
- [ ] The dashboard reflects a stopped container within 5 s.
- [ ] `make check` (ruff + pytest + web lint, type-check and production build) passes locally, and CI runs it on every push to `main` and is green.
- [ ] CI fails if regenerating the API types produces a diff.
- [ ] The dashboard reads the API base URL from env (no hardcoded host), and the API allows that origin (CORS).
- [ ] `.env` and the data-cache directory are gitignored. `.env.example` keeps the existing ERCOT entries and adds every new variable with a comment.
- [ ] The README quickstart is `make setup && make up` (no manual installs) plus the dashboard and Temporal UI URLs.

## Out of scope
Any market data, planning or dispatch logic.
