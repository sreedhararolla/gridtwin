"""Backfill DAM SPP from ERCOT's yearly historical report (NP4-180-ER).

Same story as RT (rtm_history.py): the daily NP4-190-CD documents cover only the last few
days, and the yearly "Historical DAM Load Zone and Hub Prices" zip covers the rest. The LP
Strategy plans on these prices (marketdata/forecast.py).
"""

import logging
from datetime import date

import gridstatus
import pandas as pd
from gridstatus import utils as gs_utils

from gridtwin.marketdata import cache
from gridtwin.marketdata.ercot_source import SETTLEMENT_POINTS
from gridtwin.marketdata.intervals import CENTRAL

logger = logging.getLogger(__name__)

HISTORICAL_DAM_REPORT_TYPE_ID = 13060
SOURCE = "ercot_historical"


def parse_dam_history(raw: pd.DataFrame) -> pd.DataFrame:
    """Workbook rows -> (interval_start_utc, settlement_point, price_usd_per_mwh), one row
    per hour. Hour Ending is "01:00".."24:00" Central; the Repeated Hour Flag marks the
    second (standard-time) copy of the fall-back hour."""
    df = raw.dropna(subset=["Hour Ending", "Settlement Point"], how="any")
    df = df[df["Settlement Point"].isin(SETTLEMENT_POINTS)]
    hour_ending = df["Hour Ending"].astype(str).str.split(":").str[0].astype(int)
    local = pd.to_datetime(df["Delivery Date"], format="%m/%d/%Y") + pd.to_timedelta(
        hour_ending - 1, unit="h"
    )
    first_copy = df["Repeated Hour Flag"].astype(str).str.upper().ne("Y").to_numpy()
    starts = pd.DatetimeIndex(local).tz_localize(
        CENTRAL.key, ambiguous=first_copy, nonexistent="shift_forward"
    )
    return pd.DataFrame(
        {
            "interval_start_utc": starts.tz_convert("UTC"),
            "settlement_point": df["Settlement Point"].to_numpy(),
            "price_usd_per_mwh": df["Settlement Point Price"].astype(float).to_numpy(),
        }
    )


def fetch_dam_history(year: int) -> pd.DataFrame:
    ercot = gridstatus.Ercot()
    doc = ercot._get_document(
        report_type_id=HISTORICAL_DAM_REPORT_TYPE_ID, constructed_name_contains=f"{year}.zip"
    )
    workbook = gs_utils.get_zip_file(doc.url)
    sheets = pd.read_excel(workbook, sheet_name=None)
    return parse_dam_history(pd.concat(s for s in sheets.values() if not s.empty))


def backfill_dam_spp(start: date, end: date) -> int:
    """Write every missing cached day in [start, end]. Returns the number of days written."""
    written = 0
    for year in range(start.year, end.year + 1):
        df = fetch_dam_history(year)
        trading_day = df["interval_start_utc"].dt.tz_convert(CENTRAL.key).dt.date
        for day, rows in df.groupby(trading_day):
            if not (start <= day <= end) or cache.has_day("dam_spp", "ALL", day):
                continue
            cache.write_day("dam_spp", "ALL", day, rows.reset_index(drop=True), source=SOURCE)
            written += 1
            logger.info("backfilled dam_spp/ALL/%s from NP4-180-ER", day)
    return written
