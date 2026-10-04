"""Deterministic trailing-time extraction for "remind me to ... at 4pm".

Placeholder in the same spirit as task_intent.py: it only accepts unambiguous
forms and returns no time otherwise, so the caller falls back to a plain
to-do. A bare "at 4" (no am/pm) is deliberately not accepted.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_FILLER = r"(?:\s+(?:later|today|tonight))*"
_AT = re.compile(
    rf"{_FILLER}\s+(?P<day>tomorrow\s+)?at\s+(?P<h>\d{{1,2}})(?::(?P<m>\d{{2}}))?\s*(?P<ap>am|pm)?\s*[.!]?$",
    re.IGNORECASE,
)
_IN = re.compile(r"\s+in\s+(?P<n>\d{1,3})\s+(?P<unit>minutes?|mins?|hours?|hrs?|days?)\s*[.!]?$", re.IGNORECASE)
_TOMORROW = re.compile(r"\s+tomorrow\s*[.!]?$", re.IGNORECASE)


def split_reminder_time(text: str, now: datetime, timezone: str) -> tuple[str, datetime | None]:
    """Return (text without the time phrase, due time or None)."""
    text = text.strip()
    local_now = now.astimezone(ZoneInfo(timezone))

    match = _IN.search(text)
    if match:
        unit = match["unit"].lower()
        step = timedelta(minutes=1) if unit.startswith("m") else timedelta(hours=1) if unit.startswith("h") else timedelta(days=1)
        return text[: match.start()].strip(), now + int(match["n"]) * step

    match = _AT.search(text)
    if match:
        hour, minute, meridiem = int(match["h"]), int(match["m"] or 0), (match["ap"] or "").lower()
        if minute > 59 or (not meridiem and not match["m"]):
            return text, None
        if meridiem:
            if not 1 <= hour <= 12:
                return text, None
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        elif hour > 23:
            return text, None
        due = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if match["day"] or due <= local_now:
            due += timedelta(days=1)
        return text[: match.start()].strip(), due

    match = _TOMORROW.search(text)
    if match:
        due = (local_now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        return text[: match.start()].strip(), due

    return text, None
