"""Probability scoring for the Risk Curve: Brier, PR-AUC, calibration. Pure: no IO."""

import numpy as np

from gridtwin.risk.models import CalibrationBin

CALIBRATION_EDGES = (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 1.0)


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2)) if len(y) else float("nan")


def pr_auc(y: np.ndarray, p: np.ndarray) -> float | None:
    """Average precision (step-wise area under the precision-recall curve), None with no
    positives. Ties are broken in a fixed order so the number is reproducible."""
    positives = int(y.sum())
    if positives == 0:
        return None
    order = np.argsort(-p, kind="stable")
    hits = y[order]
    tp = np.cumsum(hits)
    precision = tp / np.arange(1, len(hits) + 1)
    return float(np.sum(precision * hits) / positives)


def calibration(y: np.ndarray, p: np.ndarray) -> list[CalibrationBin]:
    """Mean predicted vs observed spike rate per probability bin (bins are narrow at the
    low end, where almost every prediction lives)."""
    bins = []
    edges = CALIBRATION_EDGES
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (p >= lo) & ((p < hi) if hi < 1.0 else (p <= hi))
        n = int(mask.sum())
        bins.append(
            CalibrationBin(
                lo=lo,
                hi=hi,
                count=n,
                mean_predicted=float(p[mask].mean()) if n else 0.0,
                observed_rate=float(y[mask].mean()) if n else 0.0,
            )
        )
    return bins
