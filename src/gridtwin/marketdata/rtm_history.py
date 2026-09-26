"""Backfill RT SPP from ERCOT's yearly historical report (NP6-785-ER).

ERCOT's MIS keeps only the last ~9 days of the daily RT SPP report (NP6-905-CD), so the
daily fetcher can't reach most of the post-RTC+B window. The yearly "Historical RTM Load
Zone and Hub Prices" zip covers the whole year for hubs and load zones. gridstatus's own
`get_rtm_spp(year)` crashes on current pandas, so this parses the workbook directly.
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

HISTORICAL_RTM_REPORT_TYPE_ID = 13061
SOURCE = "ercot_historical"
SETTLEMENT_POINT_TYPES = {"LZ", "HU"}


def parse_rtm_history(raw: pd.DataFrame) -> pd.DataFrame:
    """Workbook rows -> (interval_start_utc, settlement_point, price_usd_per_mwh).

    Delivery Hour is hour-ending 1..24 in Central time; Delivery Interval is 1..4; the
    Repeated Hour Flag marks the second (standard-time) copy of the fall-back hour.
    """
    df = raw.dropna(subset=["Delivery Hour", "Delivery Interval"], how="any").copy()
    # Load zones appear twice: LZ (the settlement price) and LZEW (energy-weighted); keep LZ.
    df = df[
        df["Settlement Point Name"].isin(SETTLEMENT_POINTS)
        & df["Settlement Point Type"].isin(SETTLEMENT_POINT_TYPES)
    ]
    local = (
        pd.to_datetime(df["Delivery Date"], format="%m/%d/%Y")
        + pd.to_timedelta(df["Delivery Hour"].astype(int) - 1, unit="h")
        + pd.to_timedelta((df["Delivery Interval"].astype(int) - 1) * 15, unit="m")
    )
    first_copy = df["Repeated Hour Flag"].astype(str).str.upper().ne("Y").to_numpy()
    starts = pd.DatetimeIndex(local).tz_localize(
        CENTRAL.key, ambiguous=first_copy, nonexistent="shift_forward"
    )
    return pd.DataFrame(
        {
            "interval_start_utc": starts.tz_convert("UTC"),
            "settlement_point": df["Settlement Point Name"].to_numpy(),
            "price_usd_per_mwh": df["Settlement Point Price"].astype(float).to_numpy(),
        }
    )


def fetch_rtm_history(year: int) -> pd.DataFrame:
    ercot = gridstatus.Ercot()
    doc = ercot._get_document(
        report_type_id=HISTORICAL_RTM_REPORT_TYPE_ID, constructed_name_contains=f"{year}.zip"
    )
    workbook = gs_utils.get_zip_file(doc.url)
    sheets = pd.read_excel(workbook, sheet_name=None)
    return parse_rtm_history(pd.concat(sheets.values()))


def backfill_rt_spp(start: date, end: date) -> int:
    """Write every missing cached day in [start, end] from the yearly reports. Returns the
    number of days written. Days already cached (e.g. from the daily fetch) are kept."""
    written = 0
    for year in range(start.year, end.year + 1):
        df = fetch_rtm_history(year)
        trading_day = df["interval_start_utc"].dt.tz_convert(CENTRAL.key).dt.date
        for day, rows in df.groupby(trading_day):
            if not (start <= day <= end) or cache.has_day("rt_spp", "ALL", day):
                continue
            cache.write_day("rt_spp", "ALL", day, rows.reset_index(drop=True), source=SOURCE)
            written += 1
            logger.info("backfilled rt_spp/ALL/%s from NP6-785-ER", day)
    return written
