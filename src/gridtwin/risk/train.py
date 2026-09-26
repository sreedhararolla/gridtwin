"""`make train`: the scarcity-risk model, from the cache, reproducibly (fixed seed).

Builds one row per (decision interval, target interval in the next 4 h) with the pure
feature builder, labels a target a spike when its RT SPP exceeds the training window's
99th percentile, and scores a calibrated LightGBM classifier against hour-of-day
climatology with monthly walk-forward CV. Months without enough history before them get
a leave-month-out fit instead, so every cached interval has an out-of-sample Risk Curve;
those folds are flagged and kept out of the headline metrics.

Writes (all derived from the cache, never committed):
  data/cache/risk/predictions.parquet   out-of-sample Risk Curves, read live and by the backtest
  data/cache/risk/model.joblib          the deployed model, fit on every cached day
  data/cache/insights/risk_report.json  the RiskReport MODEL.md quotes

uv run python -m gridtwin.risk.train [--settlement-point LZ_HOUSTON]
"""

import argparse
import hashlib
import logging
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import duckdb
import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV

from gridtwin.marketdata import cache
from gridtwin.risk import metrics
from gridtwin.risk.features import (
    FEATURE_NAMES,
    HORIZON_INTERVALS,
    RT_LOOKBACK_INTERVALS,
    KnownInputs,
    Obs,
    build_features,
    dam_known_at,
    rt_known_at,
    spike_threshold,
    targets_from,
    temperature_known_at,
    trading_day,
)
from gridtwin.risk.models import FoldResult, RiskReport, ScoreCard
from gridtwin.risk.paths import predictions_path, report_path, risk_dir
from gridtwin.settings import settings

logger = logging.getLogger(__name__)

QUANTILE = 0.99
MIN_TRAIN_MONTHS = 2
MISSING_INPUTS = [
    "forecast net load (load - wind - solar forecast): load/wind/solar forecasts are not "
    "cached; the keyless archive only keeps the latest vintage (DATA.md) and ingest has "
    "not run for them",
    "outage capacity (NP3-233-CD): not cached",
    "net-load ramp slope: needs the net-load forecast above",
]
HOUR_HOLD_TEMPS = 4


def _series(dataset: str, where: str, value: str) -> pd.DataFrame:
    glob = str(cache.cache_root() / dataset / "**" / "*.parquet")
    df = duckdb.sql(
        f"SELECT interval_start_utc AS ts, {value} AS val "
        f"FROM read_parquet('{glob}', union_by_name=true) WHERE {where} ORDER BY ts"
    ).df()
    df = df.rename(columns={"ts": "at", "val": "value"})
    df["at"] = pd.to_datetime(df["at"], utc=True)
    return df.drop_duplicates("at")


def _obs(df: pd.DataFrame, known_at) -> list[Obs]:
    return [
        Obs(at, known_at(at), float(v))
        for at, v in zip((t.to_pydatetime() for t in df["at"]), df["value"], strict=True)
    ]


@dataclass
class History:
    rt: list[Obs]
    dam_by_day: dict[date, list[Obs]]
    temperature: list[Obs]

    def known_at(self, decision: datetime) -> KnownInputs:
        """Exactly what had been published by `decision` (and no more than needed)."""
        rt_idx = bisect_right(self._rt_known, decision)
        temp_idx = bisect_right(self._temp_known, decision)
        today = trading_day(decision)
        dam = [
            o
            for day in (today, today + timedelta(days=1))
            for o in self.dam_by_day.get(day, [])
            if o.known_at <= decision
        ]
        return KnownInputs(
            rt=self.rt[max(0, rt_idx - RT_LOOKBACK_INTERVALS) : rt_idx],
            dam=dam,
            temperature=self.temperature[max(0, temp_idx - HOUR_HOLD_TEMPS) : temp_idx],
        )

    def __post_init__(self) -> None:
        self._rt_known = [o.known_at for o in self.rt]
        self._temp_known = [o.known_at for o in self.temperature]


def load_history(settlement_point: str, city: str) -> History:
    post = f"interval_start_utc >= TIMESTAMP '{cache.RTCB_GO_LIVE.isoformat()}'"
    rt = _series("rt_spp", f"settlement_point = '{settlement_point}'", "price_usd_per_mwh")
    dam = _series("dam_spp", f"settlement_point = '{settlement_point}'", "price_usd_per_mwh")
    temp = _series("weather_temperature", f"city = '{city}' AND {post}", "temperature_c")
    dam_by_day: dict[date, list[Obs]] = defaultdict(list)
    for at, v in zip((t.to_pydatetime() for t in dam["at"]), dam["value"], strict=True):
        day = trading_day(at)
        dam_by_day[day].append(Obs(at, dam_known_at(day), float(v)))
    return History(
        rt=[o for o in _obs(rt, rt_known_at) if trading_day(o.at) >= cache.RTCB_GO_LIVE],
        dam_by_day=dict(dam_by_day),
        temperature=_obs(temp.dropna(), temperature_known_at),
    )


def build_dataset(history: History) -> pd.DataFrame:
    """One row per (decision, target) where the target's RT price is known (the label)."""
    price_at = {o.at: o.value for o in history.rt}
    dam_at = {o.at: o.value for day in history.dam_by_day.values() for o in day}
    first_day = trading_day(history.rt[0].at) + timedelta(days=1)  # a day of RT history
    records: list[list] = []
    for obs in history.rt:
        decision = obs.at
        if trading_day(decision) < first_day:
            continue
        rows = build_features(decision, history.known_at(decision))
        for target, row in zip(targets_from(decision), rows, strict=True):
            price = price_at.get(target)
            if price is None:
                continue
            dam = dam_at.get(target.replace(minute=0))
            records.append([decision, target, price, np.nan if dam is None else dam, *row])
    df = pd.DataFrame(
        records, columns=["decision_utc", "target_utc", "rt_price", "dam_price", *FEATURE_NAMES]
    )
    df["month"] = df["month"].astype(float)
    df["decision_month"] = df["decision_utc"].map(lambda t: trading_day(t).strftime("%Y-%m"))
    df["target_month"] = df["target_utc"].map(lambda t: trading_day(t).strftime("%Y-%m"))
    return df


def _model(seed: int) -> CalibratedClassifierCV:
    booster = LGBMClassifier(
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=15,
        min_child_samples=100,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        random_state=seed,
        n_jobs=1,
        deterministic=True,
        force_row_wise=True,
        verbose=-1,
    )
    return CalibratedClassifierCV(booster, method="sigmoid", cv=3)


def _climatology(train: pd.DataFrame, labels: np.ndarray, test: pd.DataFrame) -> np.ndarray:
    """Hour-of-day spike frequency in the training window (smoothed toward the base rate)."""
    hours = np.floor(train["hour_ct"].to_numpy()).astype(int)
    base = labels.mean()
    counts = np.bincount(hours, minlength=24)
    hits = np.bincount(hours, weights=labels, minlength=24)
    rate = (hits + 10 * base) / (counts + 10)
    return rate[np.floor(test["hour_ct"].to_numpy()).astype(int)]


def _spike_premium(train: pd.DataFrame, threshold: float) -> float:
    targets = train.drop_duplicates("target_utc")
    spikes = targets[targets["rt_price"] > threshold]
    premium = (spikes["rt_price"] - spikes["dam_price"]).dropna()
    return float(premium.mean()) if len(premium) else 0.0


def _score(y: np.ndarray, p: np.ndarray) -> ScoreCard:
    return ScoreCard(
        brier=metrics.brier(y, p),
        pr_auc=metrics.pr_auc(y, p),
        calibration=metrics.calibration(y, p),
    )


def _fit_predict(
    train: pd.DataFrame, test: pd.DataFrame, seed: int
) -> tuple[np.ndarray, np.ndarray, float, float, np.ndarray]:
    prices = train.drop_duplicates("target_utc")["rt_price"].tolist()
    threshold = spike_threshold(prices, QUANTILE)
    y_train = (train["rt_price"].to_numpy() > threshold).astype(int)
    y_test = (test["rt_price"].to_numpy() > threshold).astype(int)
    model = _model(seed)
    model.fit(train[list(FEATURE_NAMES)], y_train)
    p = model.predict_proba(test[list(FEATURE_NAMES)])[:, 1]
    clim = _climatology(train, y_train, test)
    return y_test, p, threshold, _spike_premium(train, threshold), clim


def walk_forward(df: pd.DataFrame, seed: int) -> tuple[list[FoldResult], pd.DataFrame]:
    months = sorted(df["decision_month"].unique())
    folds: list[FoldResult] = []
    predictions: list[pd.DataFrame] = []
    for i, month in enumerate(months):
        test = df[df["decision_month"] == month]
        if i >= MIN_TRAIN_MONTHS:
            provenance = "walk-forward"
            # Purge rows whose target falls in the test month (their label is test data).
            train = df[(df["decision_month"] < month) & (df["target_month"] < month)]
        else:
            provenance = "leave-month-out"
            train = df[(df["decision_month"] != month) & (df["target_month"] != month)]
        y, p, threshold, premium, clim = _fit_predict(train, test, seed)
        logger.info(
            "%s %s: train %d rows, test %d rows, %d spikes, threshold $%.2f",
            month, provenance, len(train), len(test), int(y.sum()), threshold,
        )  # fmt: skip
        folds.append(
            FoldResult(
                test_month=month,
                provenance=provenance,
                train_rows=len(train),
                test_rows=len(test),
                threshold_usd_per_mwh=threshold,
                spike_premium_usd_per_mwh=premium,
                test_positive_rate=float(y.mean()),
                model=_score(y, p),
                climatology=_score(y, clim),
            )
        )
        predictions.append(
            pd.DataFrame(
                {
                    "decision_utc": test["decision_utc"].to_numpy(),
                    "target_utc": test["target_utc"].to_numpy(),
                    "lead": test["lead_intervals"].astype(int).to_numpy(),
                    "rt_price": test["rt_price"].to_numpy(),
                    "spike": y,
                    "p_spike": p,
                    "p_climatology": clim,
                    "threshold_usd": threshold,
                    "premium_usd": premium,
                    "provenance": provenance,
                    "test_month": month,
                }
            )
        )
    return folds, pd.concat(predictions, ignore_index=True)


def fingerprint(predictions: pd.DataFrame) -> str:
    rounded = np.round(predictions["p_spike"].to_numpy(), 10)
    return hashlib.sha256(rounded.tobytes()).hexdigest()


def train(settlement_point: str, seed: int, city: str) -> tuple[RiskReport, pd.DataFrame]:
    history = load_history(settlement_point, city)
    df = build_dataset(history)
    logger.info("dataset: %d rows, %d decisions", len(df), df["decision_utc"].nunique())
    folds, predictions = walk_forward(df, seed)
    predictions["settlement_point"] = settlement_point

    wf = predictions[predictions["provenance"] == "walk-forward"]
    y = wf["spike"].to_numpy()
    model_card = _score(y, wf["p_spike"].to_numpy())
    clim_card = _score(y, wf["p_climatology"].to_numpy())

    # The deployed model: every cached day, the all-data threshold.
    all_prices = df.drop_duplicates("target_utc")["rt_price"].tolist()
    threshold = spike_threshold(all_prices, QUANTILE)
    final = _model(seed)
    final.fit(df[list(FEATURE_NAMES)], (df["rt_price"].to_numpy() > threshold).astype(int))
    risk_dir().mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": final, "features": list(FEATURE_NAMES), "threshold_usd": threshold},
        risk_dir() / "model.joblib",
    )

    days = sorted({trading_day(t) for t in df["target_utc"]})
    report = RiskReport(
        settlement_point=settlement_point,
        start_day=days[0],
        end_day=days[-1],
        seed=seed,
        quantile=QUANTILE,
        horizon_intervals=HORIZON_INTERVALS,
        features=list(FEATURE_NAMES),
        missing_inputs=MISSING_INPUTS,
        threshold_usd_per_mwh=threshold,
        folds=folds,
        walk_forward_rows=len(wf),
        walk_forward_positive_rate=float(y.mean()) if len(y) else 0.0,
        model=model_card,
        climatology=clim_card,
        brier_skill_vs_climatology=1.0 - model_card.brier / clim_card.brier
        if clim_card.brier
        else 0.0,
        predictions_sha256=fingerprint(predictions),
    )
    return report, predictions


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="gridtwin.risk.train")
    parser.add_argument("--settlement-point", default=settings.settlement_point)
    parser.add_argument("--seed", type=int, default=settings.risk_seed)
    args = parser.parse_args()

    report, predictions = train(args.settlement_point, args.seed, settings.risk_weather_city)
    risk_dir().mkdir(parents=True, exist_ok=True)
    out = predictions_path()
    tmp = out.with_suffix(".parquet.tmp")
    duckdb.sql("SELECT * FROM predictions ORDER BY decision_utc, lead").write_parquet(str(tmp))
    tmp.replace(out)
    report_path().parent.mkdir(parents=True, exist_ok=True)
    report_path().write_text(report.model_dump_json(indent=2))

    print(f"{report.settlement_point} {report.start_day} -> {report.end_day}, seed {report.seed}")
    header = ("month", "fold", "spike %", "Brier", "clim", "PR-AUC", "clim")
    print("{:<8} {:<16} {:>8} {:>8} {:>8} {:>7} {:>7}".format(*header))
    for f in report.folds:
        print(
            f"{f.test_month:<8} {f.provenance:<16} {100 * f.test_positive_rate:>7.2f}% "
            f"{f.model.brier:>8.5f} {f.climatology.brier:>8.5f} "
            f"{_fmt(f.model.pr_auc):>7} {_fmt(f.climatology.pr_auc):>7}"
        )
    print(
        f"walk-forward pooled ({report.walk_forward_rows} rows, "
        f"{100 * report.walk_forward_positive_rate:.2f}% spikes): "
        f"Brier {report.model.brier:.5f} vs climatology {report.climatology.brier:.5f} "
        f"(skill {report.brier_skill_vs_climatology:+.3f}); "
        f"PR-AUC {_fmt(report.model.pr_auc)} vs {_fmt(report.climatology.pr_auc)}"
    )
    print("calibration (model): predicted -> observed (n)")
    for b in report.model.calibration:
        predicted, observed = b.mean_predicted, b.observed_rate
        print(f"  [{b.lo:.2f}, {b.hi:.2f}) {predicted:.4f} -> {observed:.4f} ({b.count})")
    print(f"predictions sha256 {report.predictions_sha256}")
    print(f"wrote {out} and {report_path()}")


if __name__ == "__main__":
    main()
