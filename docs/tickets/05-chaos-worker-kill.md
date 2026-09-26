# 05: Chaos panel + worker-kill resilience

**Type:** AFK · **Priority:** P0 · **Blocked by:** 04 · **User stories:** 7, 11, 12, 18

## What to build
- **Chaos controller.** A service with an API to apply and clear Chaos Scenarios, and a `chaos_events` log. It uses the Docker Engine API through a mounted socket: local demo only, documented.
- **Dashboard.** A chaos panel of buttons, an event timeline and an **SLO table** (target vs actual for within-tolerance %, reserve violations and recovery time).
- **First scenario: kill a worker** mid-interval, then auto-restart it after a configurable delay. Tune activity timeouts, heartbeats and retry policy so the work moves to the surviving worker. Measure **recovery time**.
- **Scripted scenarios.** A small YAML format ("at interval k, apply X for n intervals"), runnable via `make chaos SCENARIO=<name>` and by the Scenario Runner in compose mode.

Tracer bullet first: one button → one kill → one event on the timeline. Then make recovery measurable.

## Demo path
During the spike on the top demo day, click **Kill worker**. The worker dot drops to 1/2 and no interval is missed. The recovery time appears in the SLO table, and the Temporal UI shows the retried activity.

## Acceptance criteria
- [ ] Killing a worker mid-dispatch skips no interval. The affected activity completes on the other worker, as the retry in Temporal history shows.
- [ ] Recovery time is measured and displayed. Every chaos event records its time, scenario and target.
- [ ] `make chaos SCENARIO=worker-kill` runs deterministically and prints a Scenario Report.
- [ ] An e2e test (compose mode, marked `e2e`) passes the SLOs under the worker-kill scenario.
- [ ] The scenario YAML format is documented in the README.

## Out of scope
Device, telemetry and feed faults (tickets 06–08).
