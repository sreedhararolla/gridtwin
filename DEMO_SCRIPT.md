# GridTwin: demo video script (5:00)

The beats follow the spec's demo storyline. **Cue** is what is on screen; **Say** is the
voice-over. Record at 1080p with the browser at 100 % zoom, and do two takes.

## Before you record

```
make up                   # whole stack; wait for every dot on the Live page to go green
make demo-full            # dry run: ~10 min, must end with every SLO row PASS
```

Keep these tabs open, left to right:
1. Dashboard **Insights**: http://localhost:3000/insights
2. Dashboard **Live**: http://localhost:3000/live
3. **Temporal UI**: http://localhost:8080
4. A terminal in the repo, font at 16 pt or more.

During take 1, `make demo-full` drives the chaos for you, so every fault lands on the same
interval every take. To drive it by hand instead, pick 2026-01-28 on the Live page, press
**Replay** and use the chaos panel buttons at the times below.

## 0:00–0:30 Hook: value concentrates in a few spike intervals (ticket 11)

- **Cue:** the Insights tab, headline at the top.
- **Say:** "After ERCOT's RTC+B go-live, the top 1 % of 15-minute intervals hold 28 % of a
  battery fleet's value, and the top 5 % hold over half. If your dispatch is down during
  those few intervals, you lose most of the year's money. So a VPP's real job is
  reliability at the spike."

## 0:30–1:15 Insight: concentration, downtime cost, the Risk Curve (tickets 11, 10)

- **Cue:** scroll to the value-concentration chart, then hover the brightest cell of the
  downtime-cost heatmap (8 PM, Apr 2026).
- **Say:** "This is what a minute of downtime costs by hour and month: $20 a minute on
  average at 8 PM in April, $105 at p95. It gives on-call a price tag."
- **Cue:** Live tab, the Risk Curve panel ahead of the Jan 28, 7:00 AM spike.
- **Say:** "Our scarcity-risk model ranks spike risk about four times better than
  climatology, so the operator sees the spike coming. It is a risk monitor; MODEL.md says
  honestly why we don't trade on it yet."

## 1:15–2:00 Architecture and Temporal live (tickets 02, 04)

- **Cue:** the README's Mermaid diagram on GitHub, then the Temporal UI workflow list.
- **Say:** "Real ERCOT prices are replayed from a local cache. Each 15-minute Market
  Interval is a Temporal workflow. It plans one fleet MW target, then fans out 20 Shard
  dispatch activities over NATS to 2,000 simulated Base Core batteries. Every Command
  carries an Idempotency Key and lands in a Postgres Command Ledger."
- **Cue:** open one `interval:` workflow and show its 20 `dispatch_shard` activities.

## 2:00–3:45 Chaos on the top spike day (tickets 05–08)

Start `make demo-full` in the terminal just before this beat (or at 1:15, so the kill
lands on camera). It replays Jan 28, 2026 from 6:00 AM CT at 60x.

| Replay time (CT) | Fault | Cue | Say |
|---|---|---|---|
| 7:00 AM, the $1,284/MWh peak | **Worker kill** | Worker dot drops to 1/2; chaos timeline marker | "We SIGKILL the worker mid-dispatch, at the peak. Temporal retries the Shard on the surviving worker. No interval is skipped." If the terminal lists a retried attempt, open it in the Temporal UI (`attempt: 2`). If not, the killed Shard had already finished; say "recovered in 0.3 s" from the event timeline instead. |
| 8:15 AM | **Partition 20 %** | Online devices drop to 1,600; Fleet timeline "400 devices stale" | "A fifth of the fleet goes dark. Those Devices go stale and leave Fleet State, so we never plan on capacity that may not exist. Any Shortfall is reallocated to reachable Devices." |
| 10:30 AM | **Duplicate commands** | Duplicate deliveries counter climbs; Duplicate effects stays 0 | "Every batch is delivered twice and old ones are replayed. Devices dedupe by Idempotency Key, so effects stay at zero." |
| 12:45 PM | **Feed outage** | Degradation badge L0 → L1 → L2, then back to L0 | "The ERCOT feed breaks. We step down the Degradation Ladder: Cached Plan, then Safe Rule. The circuit breaker probes, and we climb back to L0." |

## 3:45–4:30 Results: SLO table, backtest, benchmarks (tickets 09, 12)

- **Cue:** the terminal as `make demo-full` finishes: Scenario Report, chaos events,
  retried dispatch attempts and the SLO table, every row PASS.
- **Say:** "Four faults in one run. Deliveries within tolerance, zero reserve violations,
  zero duplicate effects, zero missed intervals, recovery inside the SLO."
- **Cue:** the Insights tab's backtest table.
- **Say:** "The LP planner earns $2,173 per MW-month against $1,192 for a naive schedule.
  That's 57 % of perfect foresight; the rest is RT spikes that nobody priced day-ahead."

## 4:30–5:00 Why Base (ticket 13)

- **Cue:** the README's "What's real vs simulated" section, then the terminal running
  `make up && make demo-full`.
- **Say:** "This is Base's market infrastructure problem: many batteries, one market,
  and failures that cost the most exactly when prices spike. It's all one command, on
  real ERCOT data, and it's honest about what's simulated."
