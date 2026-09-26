# 11: Insights: what most people miss

**Type:** AFK · **Priority:** P0 · **Blocked by:** 03 · **User stories:** 16, 17

## What to build
Offline analyses (`make insights`) on the cache, rendered in the Insights tab and exported as CSV/PNG for the README and video:
1. **Value concentration.** Per-interval opportunity = fleet power × max(0, RT SPP − that day's median RT SPP) × 0.25 h. Report the share of window value in the top 1% and 5% of intervals and in the top 10 days. Compare pre- vs post-RTC+B if pre-RTC+B data is cached.
2. **Downtime-cost heatmap.** Expected $ lost per minute of dispatch outage, by hour of day × month, as mean and p95, for the 2,000-device fleet.
3. **Forecast error vs price.** A scatter of forecast net-load error against RT SPP, highlighting spike intervals. Only if forecast history is cached; otherwise the tab shows "needs ERCOT keys" and the ticket still completes.

Definitions and formulas appear on the tab and in the README.

## Demo path
Open the Insights tab and read the headline: "Top 1% of intervals hold X% of the value; a minute of downtime at 7 PM in August costs $Y."

## Acceptance criteria
- [ ] `make insights` runs from cache in under 60 s.
- [ ] Headline numbers are computed, never hardcoded (test on the fixture).
- [ ] Tab values match the exported CSVs.
- [ ] Formulas are documented alongside the charts.
