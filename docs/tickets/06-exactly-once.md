# 06: Exactly-once effects under retries and duplicates

**Type:** AFK · **Priority:** P0 · **Blocked by:** 05 · **User stories:** 5, 6, 11

## What to build
Harden command delivery so that at-least-once transport gives exactly-once **effects**:
- **Ledger.** Unique on Idempotency Key, with upserts.
- **Devices.** Apply a key at most once, and ignore expired or superseded (lower `seq`) Commands.
- **Retries.** A retry after a partial send re-sends the **same** keys.
- **Chaos scenario "Duplicate commands."** Simulators deliver each batch twice and occasionally replay an old batch.
- **Dashboard.** Counters for **duplicate deliveries** vs **duplicate effects**, and a per-interval ledger summary (issued/acked/expired/failed).

## Demo path
Toggle **Duplicate commands**. The deliveries counter climbs while effects stay at 0. Open the ledger summary for any interval.

## Acceptance criteria
- [ ] Re-issuing a Command with the same key never creates a second ledger row (test).
- [ ] Domain tests: a device applies each key at most once and ignores expired and superseded Commands.
- [ ] A test hook forces an activity retry after a partial send, and the result is `duplicate_effects == 0`.
- [ ] Under the duplicate scenario, the Scenario Report shows `duplicate_deliveries > 0` and `duplicate_effects == 0`.
- [ ] The ledger summary is visible in the dashboard or via CLI.

## Out of scope
Reallocation (ticket 07).
