# GridTwin: Instructions for Claude Code

GridTwin is a fault-tolerant VPP dispatch orchestrator. It uses real, replayed post-RTC+B ERCOT data to drive a simulated fleet of Base Power batteries on Temporal, and it demonstrates resilience under injected failures. It is a hackathon project: **submission is due Sun Sep 27, 11:00 AM CT.** Favour working, demoable slices over completeness.

## Read order (every session)
1. `CONTEXT.md`: the domain language. Use these nouns in code, commits and UI.
2. The **one** ticket you are working on (`docs/tickets/NN-*.md`) and its GitHub issue.
3. Only the sections of `docs/SPEC.md` the ticket needs.

Don't read other tickets unless you are checking blockers.

## Work in tracer bullets
- Before coding, post a short plan (3–6 lines). The first item is the **tracer bullet**: the thinnest path through every layer this ticket touches (data → planner → workflow → transport → device → ledger → API → UI, as applicable). Expansions come after it.
- Make the tracer bullet **run end-to-end and pass** before widening. Actually run it and read the output.
- If you notice you are building a layer that nothing calls yet, stop and reconnect to the running path.
- **One ticket per session.** The human runs `/clear` between tickets.
- Stay in scope. If the ticket is wrong, too big or blocked, stop, comment on the issue and propose a split. Don't expand silently.

## Make targets (the public interface)
`setup` `up` `down` `logs` `check` `test` `test-e2e` `types` `demo` `demo-full` `data` `chaos` `backtest` `train` `insights` `bench`. Tickets create these progressively, so a missing target is expected until its ticket lands.

## Code conventions
- Python 3.12, `uv`, `ruff` (format + lint), type hints everywhere, `pydantic` models at boundaries.
- **Pure domain code** (planner, device model, disaggregation, feed validator, circuit breaker, feature builder) imports no IO libraries.
- **Temporal workflows are deterministic.** No IO, no wall clock, no `random`, no network inside workflows. Use Temporal's time and sleep APIs, and put all IO in activities.
- Config comes from env through a single settings module, with defaults; mirror every variable in `.env.example`.
- Tests live only at **Seam A** (Scenario Report) and **Seam B** (pure domain); see the spec's Testing Decisions. Seed all randomness.
- Structured JSON logs carrying `run_id`, `interval_start` and `shard` where relevant.
- **Web** (`web/` app): Next.js App Router, TypeScript strict, Tailwind, Recharts.
  - Use client components only where they need state or the event stream.
  - Import API types **only** from the generated file, never hand-written. Run `make types` after any API change.
  - Charts: Recharts. Build the heatmap as a small custom SVG component.
- **UI taste.** An ops-console look that stays legible in a 1080p screen recording.
  - Keep the same colour meaning on every chart: one colour each for price, target and delivered; red only for violations and errors; chaos events as timeline markers.
  - Every number shows its unit (MW, MWh, $/MWh, %).
- **No runtime network in the demo:** no CDN scripts and no `next/font/google`.
- **Never** commit secrets or cached data, and never print API key values.

## Git and ticket workflow (trunk-based; see ADR-006)
`/ship-ticket` runs this. The rules:
- Work **directly on `main`**. Commit locally in small steps, and **push only when `make check` is green.** Every push is a backup, so never push red.
- Intermediate commits reference the issue with `Refs #<issue>`. The ticket's **final commit** includes `Closes #<issue>` and the PROGRESS.md update (status `done` + closed time).
- Before every push, run `git pull --rebase origin main`. If the rebase conflicts, stop and ask. If it pulled in new commits, re-run `make check`.
- After every push, watch CI. A red `main` is fixed forward before anything else.
- Never force-push, never rewrite pushed history, never use `--no-verify`. If a push or `gh` call fails, stop and report.
- Use conventional commits, e.g. `feat(dispatch): shard fan-out with heartbeats (Refs #12)`.
- **Parallel sessions** must use a separate clone (`gh repo clone <repo> ../gridtwin-2`), never the same folder.

## You install and run everything
- `/go` does setup, then kickoff, then starts autopilot. `/setup` runs `scripts/bootstrap.sh`, which installs uv, Python, Node and `gh` without sudo and gets Docker running.
- If a command isn't found, run `source scripts/env.sh && <command>`.
- Never ask the human to install something the bootstrap can install.

## The only human steps
Ask for these; never attempt them yourself.
- Anything needing their password or a click: a one-time admin command printed by the bootstrap, and the approval step of the GitHub sign-in.
- **Optional** ERCOT keys in `.env`.
- Answering issues labeled `needs-human`.
- Recording the video and submitting.

## Autopilot
`scripts/autopilot.sh` runs one headless session per ticket with `GRIDTWIN_AUTOPILOT=1`.
- In that mode, never wait for input: park the ticket per `ship-ticket.md` and move on.
- While autopilot is running (`.autopilot/autopilot.pid` is alive), interactive sessions are **read-only**: `/status` and answering questions only.

## When blocked
- If you are stuck for more than 20 minutes on the same problem, stop. Summarize what you tried, comment on the issue and ask (or park, in autopilot).
- Switching away from Temporal (ADR-001 fallback) needs human approval.
- If implementation contradicts the spec, don't edit the spec. Add an entry to `docs/DECISIONS.md` and flag it in the issue's evidence comment.

## Definition of done
Every acceptance criterion is ticked, each with evidence (command + short output). `make check` and CI are green. PROGRESS.md is updated. The work is on `main` and the issue is closed.
