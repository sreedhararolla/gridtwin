# 08: Feed failure + degradation ladder

**Type:** AFK · **Priority:** P1 · **Blocked by:** 05 · **User stories:** 10, 11

## What to build
- **Feed validator.** Checks range, staleness, monotonic timestamps, and outliers against the recent distribution.
- **Circuit breaker** on the replay feed: open after K failures, half-open after a cooldown.
- **Degradation Ladder** L0 Optimized → L1 Cached Plan → L2 Safe Rule → L3 Hold. It recovers upward automatically after N clean intervals, and every transition is an event.
- **Chaos scenarios.** *Feed outage* (the feed raises) and *Feed outlier* (inject a $9,999 price).
- **Dashboard.** A degradation badge on the Live tab.

## Demo path
Click **Break ERCOT feed**. The badge steps L0 → L1 → L2 as the cached plan runs out. Restore the feed and the badge climbs back to L0. Click **Inject $9,999** to get a "snapshot rejected" event and no dispatch change.

## Acceptance criteria
- [ ] The injected outlier is rejected and no Command is issued based on it (test).
- [ ] During an outage the system never issues Commands without a valid price or a still-valid plan (L3 Hold = 0 MW).
- [ ] The ladder auto-recovers to L0 after N consecutive clean intervals.
- [ ] Domain unit tests cover the circuit breaker's open and half-open transitions.
- [ ] The Scenario Report includes a degradation timeline.
