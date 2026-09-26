# 02: Tracer bullet: one real day dispatches 10 batteries

**Type:** AFK · **Priority:** P0 · **Blocked by:** 01 · **User stories:** 1, 2, 4, 6, 12

## What to build
The thinnest possible end-to-end path through **every** layer, using real data:
- **Fixture.** Check in one real post-RTC+B day of 15-minute RT settlement point prices for `LZ_HOUSTON` (a small file).
- **Replay.** `ReplayRunWorkflow` walks that day's Market Intervals at replay speed. It starts one `MarketIntervalWorkflow` per interval, with workflow id `interval:{run_id}:{interval_start}`.
- **Planner.** The **naive** strategy only: full discharge at or above a high price threshold, full charge at or below a low threshold, idle otherwise.
- **Dispatch.** One activity sends **one** Command batch over the transport (NATS in compose, in-memory in tests) to **one** shard of **10** simulated devices.
- **Devices.** Simple SoC physics with the Reserve Floor enforced on the device.
- **Acks and ledger.** Devices ack with the power they actually delivered. The ledger records each Command and its Ack, and an Interval Result is written.
- **Dashboard.** The API streams Interval Results over SSE, and the Live tab charts price, target MW and delivered MW.
- **Scenario seam.** Stand up Seam A: the in-process **Scenario Runner** (manual Clock, in-memory transport, Temporal time-skipping environment) returns a **Scenario Report**.

## Demo path
`make demo` → the Live chart animates through the day. The Temporal UI shows one completed `MarketIntervalWorkflow` per interval.

## Acceptance criteria
- [ ] `make demo` replays the fixture day end-to-end with no manual steps.
- [ ] Exactly one `MarketIntervalWorkflow` runs per interval. Starting the same interval id again is rejected or a no-op (test).
- [ ] Every ledger Command has an Ack or an explicit failure, and the count equals devices × dispatched intervals.
- [ ] The Scenario Report for the fixture day shows `reserve_violations == 0` and `intervals` equal to the fixture's interval count (in-process test in CI).
- [ ] Workflow code does no IO, wall-clock reads or randomness. All IO lives in activities, and the evidence comment on the issue confirms this.
- [ ] The Live tab updates via SSE without a page refresh.

## Out of scope
Scale beyond 10 devices, the optimizer, chaos, and the full data cache.
