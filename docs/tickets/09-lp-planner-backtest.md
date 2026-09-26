# 09: LP planner + strategy backtest

**Type:** AFK · **Priority:** P0 · **Blocked by:** 04 · **User stories:** 13, 14

## What to build
- **Rolling-horizon LP** (HiGHS via scipy) on the fleet aggregate. It maximizes value at the chosen settlement point minus degradation cost, subject to SoC dynamics, efficiency, power limits and the Reserve Floor. Its price forecast is the DAM SPP baseline; ticket 10 adds risk uplift.
- **Strategies** as pure functions: `naive`, `lp`, `perfect_foresight`. Perfect foresight is the LP run on actual RT prices, an upper bound.
- **Offline backtest** (`make backtest`) over the whole cached post-RTC+B window, at fleet-aggregate level, per day with the same starting SoC.
- **Dashboard.** The Insights tab renders the comparison. The Live tab gets a strategy selector, and the plan used each interval is stored for audit.

## Demo path
A backtest table shows $/MW-month for naive, LP and perfect foresight. Switch the live replay to `lp` on the spike day and watch the fleet hold charge into the spike.

## Acceptance criteria
- [ ] Property tests on random price vectors: LP solutions respect every constraint.
- [ ] On every backtest day, perfect-foresight value ≥ the value of every other strategy.
- [ ] A 96-interval horizon solves in under 200 ms for the fleet aggregate (recorded).
- [ ] `make backtest` writes per-day values per strategy, and the Insights tab renders them.
- [ ] If LP does not beat naive in aggregate, the README explains why honestly.

## Out of scope
The risk model (ticket 10).
