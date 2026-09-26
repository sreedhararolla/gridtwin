"""Where `make train` writes (derived from the cache, never committed). Kept apart from
`train.py` so the API and workers never import LightGBM."""

from pathlib import Path

from gridtwin.marketdata import cache


def risk_dir() -> Path:
    return cache.cache_root() / "risk"


def predictions_path() -> Path:
    return risk_dir() / "predictions.parquet"


def report_path() -> Path:
    return cache.cache_root() / "insights" / "risk_report.json"
