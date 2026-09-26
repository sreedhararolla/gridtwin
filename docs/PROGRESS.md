# Progress

`/ship-ticket` updates this table in the ticket's final commit on `main`. The **Issue** column is filled by `/kickoff`.

| # | Ticket | Priority | Blocked by | Status | Issue | Closed (CT) |
|---|---|---|---|---|---|---|
| 01 | Walking skeleton | P0 | — | done | #2 | Sat 01:30 |
| 02 | Tracer bullet: one real day dispatches 10 batteries | P0 | 01 | done | #3 | Sat 07:20 |
| 03 | ERCOT + weather data cache | P0 | 01 | done | #4 | Sat 08:06 |
| 04 | Fleet at scale + any-day replay | P0 | 02, 03 | done | #5 | Sat 04:21 |
| 05 | Chaos panel + worker-kill resilience | P0 | 04 | done | #6 | Sat 10:17 |
| 06 | Exactly-once effects under retries and duplicates | P0 | 05 | done | #7 | Sat 10:58 |
| 07 | Device dropout, stale telemetry, reallocation | P0 | 05 | done | #8 | Sat 11:58 |
| 08 | Feed failure + degradation ladder | P1 | 05 | todo | #9 | |
| 09 | LP planner + strategy backtest | P0 | 04 | todo | #10 | |
| 10 | Scarcity-risk model | P1 | 09 | todo | #11 | |
| 11 | Insights: what most people miss | P0 | 03 | todo | #12 | |
| 12 | Scale + benchmarks | P2 | 06, 07 | todo | #13 | |
| 13 | Demo scenario, README, submission | P0 | 05, 06, 07, 09, 11 | todo | #14 | |
| 14 | (Stretch) Storm mode | Stretch | 09 | todo | #15 | |

Status values: `todo` · `in-progress` · `done` · `cut`

## Target schedule (CT)
Autopilot runs tickets back-to-back in dependency order: 01 → 02 → 03 → 04 → 05 → 06/07/09/11 → 08/10 → 12 → 13. It stops starting new tickets at **Sun 08:30** (`AUTOPILOT_DEADLINE`).

| When | Checkpoint |
|---|---|
| Fri night | `/go` done; autopilot running overnight |
| Sat 11 AM–1 PM | Office hours: demo what's closed, confirm the Base Core power rating, answer any `needs-human` issues |
| Sat 6 PM | **MVP freeze target:** 01–07, 09, 11 closed. Run `/status` and apply the cut lines if behind |
| Sun 8:30 AM | Autopilot stops; human records the video (13) and **submits by 10:30** |
