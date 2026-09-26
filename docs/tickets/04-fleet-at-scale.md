# 04: Fleet at scale + any-day replay

**Type:** AFK · **Priority:** P0 · **Blocked by:** 02, 03 · **User stories:** 1, 3, 4, 8, 12

## What to build
Grow the tracer bullet into a realistic fleet:
- **Fleet size.** 2,000 devices in 20 shards across 2 simulator processes.
- **Device model.** SoC dynamics with round-trip efficiency, max power, Reserve Floor, response noise, a configurable random fault rate, and a heartbeat every replay-minute. The model is pure; the simulator does the IO.
- **Telemetry.** A telemetry ingester batches the latest state per device.
- **Fleet State.** Aggregate available charge/discharge power and energy above floor, excluding stale devices.
- **Disaggregation.** Split the target proportional to headroom.
- **Dispatch.** One concurrent dispatch activity per shard, each with heartbeats.
- **Any-day replay.** The replay feed reads any cached day chosen by CLI (`make demo DAY=YYYY-MM-DD`) or the dashboard picker.
- **Live tab.** Add a fleet SoC band (p10/median/p90), an online-device count and a per-interval dispatch latency readout.

## Demo path
Replay the #1 day from `demo-days` with 2,000 devices. The SoC band drains into the evening spike while delivered MW tracks target.

## Acceptance criteria
- [ ] Any cached day replays via CLI and via the dashboard picker.
- [ ] 20 shard activities run concurrently per interval (visible in Temporal UI).
- [ ] Property test: disaggregation never exceeds a device's available power and never plans below floor.
- [ ] Scenario Report for a full spike day without chaos shows `reserve_violations == 0` and `within_tolerance_pct >= 95`.
- [ ] Median interval dispatch finishes in under 50% of the interval's wall budget at 60x (recorded in Interval Results).

## Out of scope
Chaos, the optimizer, and scaling beyond 2,000 devices.
