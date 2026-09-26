# 10: Scarcity-risk model

**Type:** AFK · **Priority:** P1 · **Blocked by:** 09 · **User stories:** 15, 16

## What to build
- **Features known at decision time:**
  - forecast net load (load − wind − solar forecast)
  - today's forecast error so far
  - outage capacity
  - net-load ramp slope
  - hour, day and month
  - temperature
  - DAM price
- **Label.** RT SPP at the settlement point exceeds its post-RTC+B 99th percentile within the next 1–4 hours. The threshold is computed from training data and recorded.
- **Model.** LightGBM classifier with monthly walk-forward CV and calibration. Baseline: hour-of-day climatology.
- **MODEL.md** covers metrics, calibration, features, leakage caveats and limits.
- **Planner integration.** Expected price = DAM + p(spike) × mean spike premium, plus a soft SoC holdback before high-risk intervals. Adds an `lp_risk` strategy to the backtest.
- **Live tab.** A risk curve for the upcoming horizon, overlaid with realized spikes.

## Demo path
On the top spike day, the risk curve rises before the real spike. The backtest shows `lp_risk` vs `lp`.

## Acceptance criteria
- [ ] The feature builder refuses any input timestamped after decision time (guard + test).
- [ ] Walk-forward CV reports Brier score, PR-AUC and a calibration curve against climatology.
- [ ] MODEL.md reports the result honestly, including when the model does not beat climatology.
- [ ] `make train` is reproducible with a fixed seed.
- [ ] The backtest includes `lp_risk`, and the Live tab shows the risk curve.

## Cut line and credentials
If behind at Sat 2 PM, **or** if forecast or outage history is still `pending-credentials`, ship a model or heuristic built only on the data that is available (DAM price, hour/season, temperature, RT history), behind the same interface. MODEL.md says what is missing and why.
