"""When an alarm next rings: the next time the clock reads a given time on one of its repeat days.

Repeat days are weekday numbers, 0 = Monday … 6 = Sunday; an empty list means "once", i.e. the next time the clock
reads that time at all. Times are interpreted in the owner's time zone so an alarm keeps ringing at 6:30 local through
daylight-saving changes."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def next_occurrence(clock: time, repeat: list[int], timezone: str, after: datetime) -> datetime:
    zone = ZoneInfo(timezone)
    start = after.astimezone(zone).date()
    for offset in range(9):
        day: date = start + timedelta(days=offset)
        if repeat and day.weekday() not in repeat:
            continue
        candidate = datetime.combine(day, clock.replace(tzinfo=None), zone)
        if candidate > after:
            return candidate.astimezone(UTC)
    raise ValueError("no occurrence within a week")  # unreachable for valid repeat days


def clock_of(due_at: datetime, timezone: str) -> time:
    return due_at.astimezone(ZoneInfo(timezone)).time().replace(second=0, microsecond=0)


def repeat_text(repeat: list[int]) -> str:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = sorted(set(repeat))
    if not days:
        return ""
    if len(days) == 7:
        return "Every day"
    if days == [0, 1, 2, 3, 4]:
        return "Weekdays"
    if days == [5, 6]:
        return "Weekends"
    return ", ".join(names[d] for d in days)
