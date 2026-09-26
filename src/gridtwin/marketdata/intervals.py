"""Pure: enumerate a Central-time calendar day's Market Intervals in UTC.

No IO. DST is handled by converting local midnight-to-midnight through
`America/Chicago`, so a spring-forward day yields 92 intervals and a
fall-back day yields 100; a normal day yields 96.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
MARKET_INTERVAL = timedelta(minutes=15)


def market_intervals_for_day(day: date, tz: ZoneInfo = CENTRAL) -> list[datetime]:
    start_local = datetime(day.year, day.month, day.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    intervals = []
    t = start_utc
    while t < end_utc:
        intervals.append(t)
        t += MARKET_INTERVAL
    return intervals
