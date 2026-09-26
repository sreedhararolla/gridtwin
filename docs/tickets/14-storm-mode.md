# 14: (Stretch) Storm mode

**Type:** AFK · **Priority:** Stretch · **Blocked by:** 09 · **User stories:** 21

## What to build
- **Dynamic reserve.** A per-zone Reserve Floor that rises when grid tightness (risk score + outage capacity) or a severe-weather signal crosses a threshold. The planner and devices respect the dynamic floor.
- **Member card.** A "Why is your battery at 60% tonight?" card generated from structured reasons (template, no LLM).
- **Trade-off panel.** $ forgone vs backup hours gained.

## Demo path
Replay a tight evening. The reserve rises beforehand, the member card explains why, and the trade-off panel quantifies the cost.

## Acceptance criteria
- [ ] The dynamic floor is never violated (Scenario Report).
- [ ] The card text is derived from computed reasons (test).
- [ ] The trade-off numbers match the backtest.
