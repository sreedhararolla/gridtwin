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
| **Achievable Target** | min(plan target, Fleet State headroom). SLOs are measured against this. |
| **Setpoint** | The MW a single Device is asked to deliver this interval. |
| **Command** | A Setpoint plus Idempotency Key plus expiry, sent in a Shard batch. |
| **Idempotency Key** | `run_id:interval_start:device_id:seq`. `seq` increments only on reallocation. |
| **Ack** | A Device's reply: key, applied or ignored, delivered MW. |
| **Command Ledger** | Postgres record of every Command's lifecycle: issued → acked / expired / failed. |
| **Delivered MW** | Sum of acked delivered power in an interval. |
| **Shortfall** | Achievable Target − Delivered MW. |
| **Reallocation** | Re-issuing Shortfall to Devices with Headroom within the interval (`seq+1`). |
| **Heartbeat** | Periodic Device telemetry: SoC, power, health, replay time. |
| **Stale Device** | A Device that has missed N Heartbeats; excluded from Fleet State. |
| **Degradation Ladder** | L0 Optimized → L1 Cached Plan → L2 Safe Rule → L3 Hold. |
| **Chaos Scenario** | An injected fault: worker kill, partition, telemetry delay, duplicates, feed outage/outlier, scale burst. |
| **Duplicate Delivery** | The same Command arriving more than once (allowed). |
| **Duplicate Effect** | A Device acting on the same key twice (must be 0). |
| **Interval Result** | Per-interval record: target, achievable, delivered, level, counts, latency. |
| **Scenario Report** | SLO summary of a run. The system-level test seam. |
