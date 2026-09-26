# 12: Scale + benchmarks

**Type:** AFK · **Priority:** P2 · **Blocked by:** 06, 07 · **User stories:** 19

## What to build
- **Benchmark matrix** (`make bench`) at 1k, 5k, 10k and 20k devices, with shards scaling alongside. It measures:
  - per-interval dispatch latency p50/p99
  - commands per second
  - recovery time after a worker kill
  - planner solve time
  - memory over a 30-minute run
- **Tuning.** Batch size and activity concurrency.
- **Backpressure.** Bounded queues in the simulators and the telemetry ingester.
- **BENCHMARKS.md** records the results, the machine specs and the methodology.

## Demo path
`make bench` prints the matrix and writes BENCHMARKS.md.

## Acceptance criteria
- [ ] At 20k devices and 60x, every interval finishes within its wall budget, or the bench reports the maximum sustainable device count.
- [ ] Memory stays flat over a 30-minute run (reported).
- [ ] p99 latency and recovery time are reported with their methodology.
