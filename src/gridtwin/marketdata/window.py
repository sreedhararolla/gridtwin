"""Pure: the calendar days an ingest/audit run covers."""

from datetime import date, timedelta


def days_in_window(start: date, end: date) -> list[date]:
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days
