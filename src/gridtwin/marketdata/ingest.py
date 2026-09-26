"""`make data`: idempotent, resumable ingest across every registered dataset.

Re-running only fetches days that are neither already cached nor already
known to need credentials we don't have. A failed fetch is recorded as a gap
with a reason, never silently skipped, and never stops the rest of the run.
"""

import logging
from dataclasses import dataclass
from datetime import date

from gridtwin.marketdata import cache, ingest_log
from gridtwin.marketdata.registry import DatasetSpec
from gridtwin.marketdata.window import days_in_window
from gridtwin.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class IngestSummary:
    fetched: int = 0
    skipped_cached: int = 0
    skipped_pending_credentials: int = 0
    errors: int = 0


def run_ingest(
    registry: list[DatasetSpec],
    start: date,
    end: date,
    include_pre_rtcb: bool = False,
) -> IngestSummary:
    if not include_pre_rtcb:
        start = max(start, cache.RTCB_GO_LIVE)

    summary = IngestSummary()
    entries = ingest_log.load_log()

    for spec in registry:
        for key in spec.keys:
            for day in days_in_window(start, end):
                if cache.has_day(spec.name, key, day):
                    summary.skipped_cached += 1
                    continue

                if spec.credential_gated and not settings.ercot_api_configured:
                    ingest_log.record(
                        entries,
                        spec.name,
                        key,
                        day,
                        "pending-credentials",
                        f"needs ERCOT_API_USERNAME/PASSWORD/SUBSCRIPTION_KEY in .env "
                        f"to fetch {spec.report_id}",
                    )
                    summary.skipped_pending_credentials += 1
                    continue

                try:
                    df = spec.fetch(key, day)
                    cache.write_day(spec.name, key, day, df)
                    ingest_log.clear(entries, spec.name, key, day)
                    summary.fetched += 1
                    logger.info("ingested %s/%s/%s", spec.name, key, day)
                except Exception as exc:  # noqa: BLE001 - one bad day must not stop the run
                    ingest_log.record(entries, spec.name, key, day, "error", str(exc))
                    summary.errors += 1
                    logger.warning("failed %s/%s/%s: %s", spec.name, key, day, exc)

    ingest_log.save_log(entries)
    return summary


def default_window() -> tuple[date, date]:
    start = date.fromisoformat(settings.marketdata_start_date)
    end = date.today()
    return start, end
