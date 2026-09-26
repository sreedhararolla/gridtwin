# GridTwin: Domain Language

Use these nouns in code, commits, UI labels and the video. If a new concept appears, add it here in the same commit.

| Term | Meaning |
|---|---|
| **Replay Run** | One execution over a historical window at a speed multiplier (`run_id`). |
| **Replay Clock** | Maps wall time to replay time. Wall-anchored in compose mode; manual in tests. |
| **Market Interval** | A 15-minute ERCOT RT settlement interval, keyed by its UTC start. |
| **Settlement Point** | ERCOT pricing location (e.g. `LZ_HOUSTON`, `HB_NORTH`). |
| **Market Snapshot** | The validated inputs for one interval: RT/DAM prices, forecasts, outages, weather. |
| **Feed Error** | A snapshot that is missing, stale or failed validation. |
| **Device** | One simulated Base Core home battery (39.2 kWh). |
| **Shard** | A group of Devices owned by one simulator process; the dispatch unit. |
| **SoC** | State of charge, 0–100%. |
| **Reserve Floor** | Minimum SoC a Device may be dispatched to (default 20%). |
| **Headroom** | Power/energy a Device can deliver without breaching limits or the floor. |
| **Fleet State** | Aggregate headroom of non-stale Devices at decision time. |
| **Risk Curve** | Spike probability for each upcoming interval in the horizon. |
| **Strategy** | Planning policy: `naive`, `lp`, `lp_risk`, `perfect_foresight`. |
| **Fleet Plan** | MW target per interval over the planning horizon (+ discharge / − charge). |
| **Achievable Target** | min(plan target, Fleet State headroom). SLOs are measured against this. Re-rated within the interval without Unresponsive Devices. |
| **Unresponsive Device** | A Device in Fleet State that sent no Ack for its Command (e.g. partitioned). Treated as stale for the rest of the interval. |
| **Reallocation Reserve** | Share of Fleet State headroom held back from the planner, so a Shortfall has Devices with Headroom to go to. |
| **Setpoint** | The MW a single Device is asked to deliver this interval. |
| **Command** | A Setpoint plus Idempotency Key plus expiry, sent in a Shard batch. |
| **Idempotency Key** | `run_id:interval_start:device_id:seq`. `seq` increments only on reallocation. |
| **Ack** | A Device's reply: key, applied or ignored, delivered MW. |
| **Command Ledger** | Postgres record of every Command's lifecycle: issued → acked / expired / failed. |
| **Ledger Summary** | The Command Ledger for one interval: Commands issued, acked, expired, failed. |
| **Batch Reply** | A Shard's answer to a Command batch: its Acks plus duplicate-delivery/effect counts. |
| **Delivered MW** | Sum of acked delivered power in an interval. |
| **Shortfall** | Achievable Target − Delivered MW. |
| **Reallocation** | Re-issuing Shortfall to Devices with Headroom within the interval (`seq+1`). |
| **Heartbeat** | Periodic Device telemetry: SoC, power, health, replay time. |
| **Stale Device** | A Device that has missed N Heartbeats; excluded from Fleet State. |
| **Degradation Ladder** | L0 Optimized → L1 Cached Plan → L2 Safe Rule → L3 Hold. |
| **Cached Plan** | The last L0 plan's target, reusable for a few intervals (its horizon) while the feed is bad. |
| **Safe Rule** | L2: discharge only if the last valid price is at or above the threshold; never charge. |
| **Circuit Breaker** | Guards the replay feed: open after K failures (feed not called), half-open probe after a cooldown. |
| **Feed Guard** | The ladder state carried between intervals: level, clean streak, breaker, recent valid prices, Cached Plan. |
| **Chaos Scenario** | An injected fault: worker kill, partition, telemetry delay, duplicates, feed outage/outlier, scale burst. |
| **Chaos Event** | One apply or clear of a Chaos Scenario: time, scenario, target and the interval it hit. |
| **Chaos Script** | `scenarios/<name>.yaml`: at interval k, apply X for n intervals, over a replay window. |
| **Recovery Time** | From a fault until the interval it interrupted records its Interval Result. |
| **Duplicate Delivery** | The same Command arriving more than once (allowed). |
| **Duplicate Effect** | A Device acting on the same key twice (must be 0). |
| **Interval Result** | Per-interval record: target, achievable, delivered, level, counts, latency. |
| **Scenario Report** | SLO summary of a run. The system-level test seam. |
| **Opportunity** | Fleet MW × max(0, RT SPP − that trading day's median RT SPP) × 0.25 h: an interval's discharge value over a typical price that day. |
| **Value Concentration** | Share of a window's Opportunity in its top 1% / 5% of intervals and top 10 days. |
| **Storm Mode** | Optional: a Reserve Floor that rises before grid-tight or severe-weather spells (`lp_storm` in the backtest). |
| **Dynamic Reserve Floor** | The Reserve Floor Storm Mode sets per interval: the storm floor (default 60%) from `lead` intervals before a tight interval, else the base floor. Commands carry it; Devices enforce it. |
| **Reserve Reason** | A signal over its threshold (grid tight: p(spike); outages: MW; heat/cold: °C) that raised the floor. |
| **Member Card** | "Why is your battery at 60% tonight?": template text built only from Reserve Reasons and the floor. |
| **Storm Trade-off** | $ forgone (lp − lp_storm value) vs backup hours gained per home over the raised intervals, from the backtest. |
| **Downtime Cost** | Expected $ lost per minute of dispatch outage = Opportunity ÷ 15, by hour of day (CT) × month, mean and p95. |
