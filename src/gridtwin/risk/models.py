"""Risk model report and Risk Curve shapes (CONTEXT.md: Risk Curve)."""

from datetime import date, datetime

from pydantic import BaseModel


class CalibrationBin(BaseModel, frozen=True):
    lo: float
    hi: float
    count: int
    mean_predicted: float
    observed_rate: float


class ScoreCard(BaseModel, frozen=True):
    """One predictor (model or climatology) scored on one set of test rows."""

    brier: float
    pr_auc: float | None  # None when the test rows hold no spike
    calibration: list[CalibrationBin]


class FoldResult(BaseModel, frozen=True):
    test_month: str  # YYYY-MM (Central)
    provenance: str  # walk-forward | leave-month-out
    train_rows: int
    test_rows: int
    threshold_usd_per_mwh: float  # p99 of the training months' RT SPP
    spike_premium_usd_per_mwh: float  # mean RT - DAM over training spikes
    test_positive_rate: float
    model: ScoreCard
    climatology: ScoreCard


class RiskReport(BaseModel, frozen=True):
    settlement_point: str
    start_day: date
    end_day: date
    seed: int
    quantile: float
    horizon_intervals: int
    features: list[str]
    missing_inputs: list[str]  # spec features not in the cache, and why
    threshold_usd_per_mwh: float  # all-data p99, for the deployed model
    folds: list[FoldResult]
    # Pooled over walk-forward folds only (leave-month-out folds are not out-of-time).
    walk_forward_rows: int
    walk_forward_positive_rate: float
    model: ScoreCard
    climatology: ScoreCard
    brier_skill_vs_climatology: float  # 1 - Brier(model) / Brier(climatology)
    predictions_sha256: str  # reproducibility fingerprint of every stored prediction


class RiskCurve(BaseModel, frozen=True):
    """Spike probability for each upcoming Market Interval, made at `decision_time`."""

    decision_time: datetime
    p_spike: list[float]  # one per interval from decision_time on (HORIZON_INTERVALS)
    threshold_usd_per_mwh: float
    spike_premium_usd_per_mwh: float
    provenance: str  # walk-forward | leave-month-out


class RiskPoint(BaseModel, frozen=True):
    interval_start: datetime
    rt_price_usd_per_mwh: float | None
    spike: bool  # realized: RT above the threshold
    p_spike_1h_ahead: float | None  # made one hour before this interval
    curve: list[float]  # the Risk Curve made at this interval (next 4 h)


class RiskDay(BaseModel, frozen=True):
    day: date
    settlement_point: str
    threshold_usd_per_mwh: float
    provenance: str
    points: list[RiskPoint]
