# Scarcity-risk model

Ticket 10. `make train` builds it from the cache, reproducibly (seed `RISK_SEED=7`,
single-threaded deterministic LightGBM). It writes three files, all derived from the
cache and never committed:

- `data/cache/risk/predictions.parquet`: out-of-sample Risk Curves.
- `data/cache/risk/model.joblib`: the deployed model, fit on every cached day.
- `data/cache/insights/risk_report.json`: the numbers below (`GET /risk/report`).

## What it predicts

At each decision time (the start of every Market Interval), the model outputs a **Risk
Curve**. That is the probability that the LZ_HOUSTON RT SPP **spikes** in each of the next
16 intervals: the interval being decided plus the next 3 h 45 m, which covers the ticket's
"next 1–4 hours". A spike is an RT SPP above the **99th percentile of the training
window's post-RTC+B RT prices**. The threshold is computed per fold from training data
only and recorded in the report. The deployed model uses the all-data p99, which is
**$164.98/MWh**.

## Features (all known at decision time)

`risk/features.py` is pure. Every input carries the time it became known, and
`build_features` raises `LookaheadError` if any input was published after the decision
time. Seam B tests cover RT, DAM and temperature.

| Feature | Source | Known at |
|---|---|---|
| lead (intervals ahead), target hour (Central), day of week, month | calendar | always |
| DAM SPP for the target hour; that day's DAM max; their ratio | `dam_spp` | 13:30 Central the day before |
| latest RT, max RT over the last 4 h, mean RT over 24 h, RT ramp over 1 h | `rt_spp` | end of each interval |
| today's forecast error so far (mean RT − DAM over today's intervals) | `rt_spp`, `dam_spp` | end of each interval |
| latest temperature and its 3 h change (Houston) | Open-Meteo archive | end of each hour |

**Missing, per the ticket's cut line.** The cache does not have these inputs, so the model
runs without them behind the same interface:
- **Forecast net load** (load − wind − solar forecast). The keyless archive keeps only
  the latest forecast vintage (DATA.md), so using it would leak future information. Load,
  wind and solar forecasts have not been ingested for the window either.
- **Outage capacity** (NP3-233-CD). Not cached.
- **Net-load ramp slope.** It needs the net-load forecast.

The "forecast error so far" feature uses DAM as the forecast, in place of the load
forecast.

## Validation

- **Walk-forward by calendar month (Central).** Each test month is scored by a model fit
  only on earlier months. Training rows whose target falls in the test month are purged,
  because their labels belong to the test period. The walk-forward starts once two
  months of history exist, so the first test month is Feb 2026.
- **Dec 2025 and Jan 2026** have no earlier history, so each gets a **leave-month-out**
  fit on the other months. These fits are not out-of-time: they learn from later
  months. They exist only so the Live tab and the backtest have a curve for every
  cached day, including the top spike day, 2026-01-28. They are excluded from the
  headline metrics.
- **Model:** LightGBM (300 trees, 15 leaves, at least 100 rows per leaf, row and column
  subsampling), wrapped in `CalibratedClassifierCV` with sigmoid (Platt) calibration and
  3-fold cross-fitting inside the training window.
- **Baseline:** climatology by hour of day, meaning each Central hour's spike frequency
  in the training window, smoothed toward the base rate.

## Results (LZ_HOUSTON, 2025-12-06 → 2026-09-25, 451,400 rows, 28,220 decisions)

| Test month | Fold | Spike rate | Brier (model) | Brier (climatology) | PR-AUC (model) | PR-AUC (climatology) |
|---|---|---|---|---|---|---|
| 2025-12 | leave-month-out | 0.00% | 0.00004 | 0.00022 | — | — |
| 2026-01 | leave-month-out | 8.05% | 0.05963 | 0.07865 | 0.764 | 0.090 |
| 2026-02 | walk-forward | 0.00% | 0.00344 | 0.00018 | — | — |
| 2026-03 | walk-forward | 0.40% | 0.00313 | 0.00412 | 0.302 | 0.005 |
| 2026-04 | walk-forward | 1.11% | 0.00849 | 0.01092 | 0.442 | 0.019 |
| 2026-05 | walk-forward | 0.03% | 0.00139 | 0.00051 | 0.001 | 0.001 |
| 2026-06 | walk-forward | 0.07% | 0.00068 | 0.00083 | 0.045 | 0.003 |
| 2026-07 | walk-forward | 0.24% | 0.00213 | 0.00241 | 0.151 | 0.015 |
| 2026-08 | walk-forward | 1.31% | 0.01082 | 0.01262 | 0.295 | 0.057 |
| 2026-09 | walk-forward | 0.96% | 0.00889 | 0.00923 | 0.181 | 0.160 |

**Pooled walk-forward** (Feb–Sep, 363,848 rows, 0.51% spikes):
- **Brier:** 0.00479 for the model vs 0.00505 for climatology, a **Brier skill of +0.052**.
- **PR-AUC:** 0.178 vs 0.046.

**Calibration** (model, pooled walk-forward; mean predicted → observed spike rate):

| p bin | n | predicted | observed |
|---|---|---|---|
| [0.00, 0.01) | 340,410 | 0.0017 | 0.0007 |
| [0.01, 0.02) | 9,570 | 0.0142 | 0.0155 |
| [0.02, 0.05) | 6,346 | 0.0306 | 0.0370 |
| [0.05, 0.10) | 2,428 | 0.0698 | 0.0750 |
| [0.10, 0.20) | 1,842 | 0.1422 | 0.1884 |
| [0.20, 0.40) | 2,232 | 0.3032 | 0.1940 |
| [0.40, 1.00] | 1,020 | 0.5578 | 0.2510 |

## Honest reading

- **Ranking is where the model helps.** Pooled PR-AUC is about 4x climatology. When the
  model says "high risk", a spike is much likelier than at that hour on an average day.
- **Its probabilities barely beat climatology.** Brier skill is only +5%. Most of the
  gain comes in March, April, July and August.
- **It loses to climatology in the quiet months.** February and May had almost no
  spikes, and the model raised false alarms. Climatology sat near zero and scored better.
- **It is over-confident above p ≈ 0.2.** Predictions of 0.3–0.56 came true about 19–25%
  of the time. The sigmoid calibration is fit on months that include January's winter
  event, so it is miscalibrated when regimes shift. Treat high values as "elevated", not
  literal.
- **Most of the signal is persistence.** Recent RT level, the 4 h max and today's
  RT − DAM error do most of the work. The model sees an event once it has started
  better than it foresees the first spike interval. On 2026-01-28, p(spike) made one
  hour ahead rose from 0.02 at 00:00 Central (the first spike interval) to 0.21 for
  the $1,284.81 peak at 07:00. The curve rises ahead of the peak, not ahead of the
  event's onset.

## Limits and leakage caveats

- **Cut-line model.** It has no net-load forecast, outages or ramp features. Those are
  the inputs most likely to anticipate a spike's onset, rather than react to it.
- **Temperature.** Open-Meteo archive values are observations. The model uses only the
  last observed hour, never the target hour's temperature, so no forecast skill is
  assumed and nothing leaks.
- **DAM timing.** The model assumes DAM results are known at 13:30 Central the day
  before (ERCOT posts them around then). Earlier in the day, only today's DAM is used.
- **Leave-month-out curves for Dec and Jan** learn from later months. The Live tab says
  which kind of curve it is showing.
- **Small sample.** There are 32 spike days in about 10 months, clustered in January,
  April and August. Month-level metrics swing on a single event.
- **The threshold moves by fold** ($119–$229), because each fold's training window has a
  different p99. That keeps the label out-of-sample, but it means "spike" is not the
  same dollar level in every month.

## In the planner (`lp_risk`)

`lp_risk` changes two things about the LP:

- **Expected price:** DAM + p(spike) × the fold's mean spike premium (mean RT − DAM over
  training spikes), wherever the Risk Curve reaches.
- **Soft SoC holdback:** stored energy is worth `RISK_HOLDBACK_USD_PER_MWH_H` ($40) × the
  peak p(spike) over the next `RISK_HOLDBACK_LOOKAHEAD_INTERVALS` (4) intervals, per hour
  held. This is planning-only and never counted in settlement.

**Live:** the plan uses the stored curve for the decision interval. The Interval Result
shows `strategy=lp_risk` and a forecast source ending in `+risk`. With no stored curves,
it plans as `lp`.

**Backtest:** `lp_risk` re-plans every hour from the current energy, using that hour's
curve. It is scored with the same settlement as the other Strategies, so perfect
foresight still bounds it.

**Result over 295 days (`make backtest`):** `lp_risk` does **worse** than `lp`.

| Variant | Value ($) |
|---|---|
| `lp` (plan once on DAM) | 421,167 |
| hourly re-plan, no risk | 419,062 |
| + premium only | 370,861 |
| + premium × 0.25 only | 416,659 |
| + holdback only | 373,091 |
| **`lp_risk` (premium + holdback)** | **334,263** |

Both mechanisms cost money. The mean spike premium is several hundred $/MWh, so even a
5–10% risk adds $20–$50/MWh to every interval in the next four hours. The LP then sells
into ordinary prices it thinks are elevated. The holdback keeps energy back for spikes
that mostly don't arrive, which is expected given the over-confidence above p ≈ 0.2.

**The honest conclusion:** this cut-line model is informative for *ranking* and
*monitoring* risk (the Live tab), but it is not yet good enough to *trade* on through
this formula. The obvious next steps are all untested here, and tuning them on this
same window would overfit:
- recalibrate on recent months only;
- shrink the premium (for example, use the median, not the mean);
- apply the holdback only above a probability floor;
- add net-load forecasts and outages.
