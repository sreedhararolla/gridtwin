"""Parsing ERCOT's yearly RTM price workbook (NP6-785-ER): hour-ending Central time to UTC
interval starts, LZ kept over LZEW, and the repeated fall-back hour disambiguated."""

import pandas as pd

from gridtwin.marketdata.rtm_history import parse_rtm_history


def row(day: str, hour: int, interval: int, name: str, kind: str, price: float, repeated="N"):
    return {
        "Delivery Date": day,
        "Delivery Hour": hour,
        "Delivery Interval": interval,
        "Repeated Hour Flag": repeated,
        "Settlement Point Name": name,
        "Settlement Point Type": kind,
        "Settlement Point Price": price,
    }


def test_hour_ending_central_becomes_utc_interval_start_and_lzew_is_dropped():
    raw = pd.DataFrame(
        [
            row("01/28/2026", 1, 1, "LZ_HOUSTON", "LZ", 30.0),
            row("01/28/2026", 1, 1, "LZ_HOUSTON", "LZEW", 31.0),
            row("01/28/2026", 19, 2, "HB_NORTH", "HU", 1200.0),
            row("01/28/2026", 1, 1, "HB_BUSAVG", "SH", 99.0),
        ]
    )
    df = parse_rtm_history(raw)
    assert len(df) == 2
    first = df.iloc[0]
    assert str(first["interval_start_utc"]) == "2026-01-28 06:00:00+00:00"  # CST = UTC-6
    assert first["price_usd_per_mwh"] == 30.0
    # Hour-ending 19, interval 2 = 18:15 CST = 00:15 UTC next day.
    assert str(df.iloc[1]["interval_start_utc"]) == "2026-01-29 00:15:00+00:00"


def test_repeated_fall_back_hour_maps_to_two_distinct_utc_intervals():
    raw = pd.DataFrame(
        [
            row("11/01/2026", 2, 1, "LZ_HOUSTON", "LZ", 20.0, repeated="N"),
            row("11/01/2026", 2, 1, "LZ_HOUSTON", "LZ", 21.0, repeated="Y"),
        ]
    )
    starts = [str(t) for t in parse_rtm_history(raw)["interval_start_utc"]]
    assert starts == ["2026-11-01 06:00:00+00:00", "2026-11-01 07:00:00+00:00"]
