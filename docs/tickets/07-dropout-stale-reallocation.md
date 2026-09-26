# 07: Device dropout, stale telemetry, reallocation

**Type:** AFK · **Priority:** P0 · **Blocked by:** 05 · **User stories:** 8, 9, 11

## What to build
- **Staleness.** A device becomes stale after it exceeds the threshold of missed heartbeats. Stale devices are excluded from Fleet State and shown greyed out.
- **Achievable Target.** Replaces the raw plan target in SLOs.
- **Reallocation.** Bounded rounds within the interval deadline issue `seq+1` Commands to devices with headroom, respecting floor and power limits.
- **Chaos scenarios.** *Partition X%*: drop Commands and telemetry for a random set of devices. *Telemetry delay Y s*.
- **Timeline events.** Stale detection and reallocation, with MW moved and device counts.

## Demo path
Click **Partition 20%**. The online count drops, then delivered MW dips and returns to target. The timeline reads, for example, "reallocated 1.8 MW to 312 devices."

## Acceptance criteria
- [ ] Devices are excluded within one telemetry period of crossing the stale threshold.
- [ ] Partition 20% over the spike window: `within_tolerance_pct >= 95` against Achievable Target.
- [ ] Telemetry delay: `reserve_violations == 0`, and Achievable Target reflects the de-rating.
- [ ] Reallocation never breaks floor or power limits (property test), and the number of rounds is bounded by config.
- [ ] Both scenarios are scripted and pass in compose-mode e2e.

## Out of scope
Feed faults (ticket 08).
