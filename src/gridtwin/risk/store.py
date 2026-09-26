"""Out-of-sample Risk Curves that `make train` stored, for the live planner, the backtest
and the Live tab. A Replay Run replays history, so the curve the model would have made at
a decision time is exactly the stored out-of-sample one (from a model fit without that
month); see MODEL.md."""

from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache

import duckdb
import pandas as pd

from gridtwin.risk.features import trading_day
from gridtwin.risk.models import RiskCurve, RiskDay, RiskPoint, RiskReport
from gridtwin.risk.paths import predictions_path, report_path

ONE_HOUR_LEAD = 4


class RiskStore:
    def __init__(self, df: pd.DataFrame, settlement_point: str) -> None:
        self.settlement_point = settlement_point
        self.curves: dict[datetime, RiskCurve] = {}
        self.by_day: dict[date, list[datetime]] = defaultdict(list)
        self.actual: dict[datetime, tuple[float, bool]] = {}
        df = df.sort_values(["decision_utc", "lead"])
        for decision, group in df.groupby("decision_utc", sort=True):
            ts = pd.Timestamp(decision).to_pydatetime()
            first = group.iloc[0]
            self.curves[ts] = RiskCurve(
                decision_time=ts,
                p_spike=[float(p) for p in group["p_spike"]],
                threshold_usd_per_mwh=float(first["threshold_usd"]),
                spike_premium_usd_per_mwh=float(first["premium_usd"]),
                provenance=str(first["provenance"]),
            )
            self.by_day[trading_day(ts)].append(ts)
            if int(first["lead"]) == 0:
                self.actual[ts] = (float(first["rt_price"]), bool(first["spike"]))

    def day(self, day: date) -> RiskDay | None:
        decisions = self.by_day.get(day)
        if not decisions:
            return None
        points = []
        for ts in decisions:
            price, spike = self.actual.get(ts, (None, False))
            earlier = self.curves.get(ts - pd.Timedelta(minutes=15 * ONE_HOUR_LEAD))
            ahead = (
                earlier.p_spike[ONE_HOUR_LEAD]
                if earlier and len(earlier.p_spike) > ONE_HOUR_LEAD
                else None
            )
            points.append(
                RiskPoint(
                    interval_start=ts,
                    rt_price_usd_per_mwh=price,
                    spike=spike,
                    p_spike_1h_ahead=ahead,
                    curve=[round(p, 4) for p in self.curves[ts].p_spike],
                )
            )
        first = self.curves[decisions[0]]
        return RiskDay(
            day=day,
            settlement_point=self.settlement_point,
            threshold_usd_per_mwh=first.threshold_usd_per_mwh,
            provenance=first.provenance,
            points=points,
        )


@lru_cache(maxsize=1)
def _load(mtime: float) -> RiskStore | None:
    path = predictions_path()
    if not path.exists():
        return None
    df = duckdb.sql(f"SELECT * FROM read_parquet('{path.as_posix()}')").df()
    df["decision_utc"] = pd.to_datetime(df["decision_utc"], utc=True)
    settlement_point = ""
    if report_path().exists():
        settlement_point = RiskReport.model_validate_json(
            report_path().read_text()
        ).settlement_point
    return RiskStore(df, settlement_point)


def load_store() -> RiskStore | None:
    """The stored curves, reloaded when `make train` rewrites them."""
    path = predictions_path()
    return _load(path.stat().st_mtime if path.exists() else 0.0)


def risk_curve(settlement_point: str, decision_time: datetime) -> RiskCurve | None:
    store = load_store()
    if store is None or store.settlement_point != settlement_point:
        return None
    return store.curves.get(decision_time)


def risk_day(settlement_point: str, day: date) -> RiskDay | None:
    store = load_store()
    if store is None or store.settlement_point != settlement_point:
        return None
    return store.day(day)
