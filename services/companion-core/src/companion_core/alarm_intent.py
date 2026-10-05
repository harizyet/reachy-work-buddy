"""Phase 38.5 (ADR 0027): deterministic alarm phrases and the state-bound
reminder-to-alarm offer. Nothing here is model output: only a recognised
phrase, or an affirmative reply to a pending offer, creates an alarm."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_TIME = re.compile(r"(?:\bat\s+)?\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)\b|\b(?:at\s+)?(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)\b", re.IGNORECASE)
_IN = re.compile(r"\bin\s+(?P<n>\d{1,3})\s+(?P<unit>minutes?|mins?|hours?|hrs?)\b", re.IGNORECASE)
_SET = re.compile(
    r"^\s*(?:please\s+)?(?:(?:set|create|add)\s+(?:me\s+)?(?:an?\s+)?alarm\b|wake me(?:\s+up)?\b)\s*(?P<rest>.*?)[.!]?\s*$",
    re.IGNORECASE,
)
_ALARM_QUERY = re.compile(r"\b(?:what|which|show|list|any|do i have|tell me)\b.*\balarms?\b", re.IGNORECASE)
_YES = re.compile(r"^\s*(?:yes|yeah|yep|yup|sure|ok|okay|please|alright|do that|go ahead)\b", re.IGNORECASE)
_NO = re.compile(r"^\s*(?:no|nope|nah|not now|don'?t|never mind|no thanks)\b", re.IGNORECASE)


OFFER_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class AlarmOffer:
    """One pending "want an alarm for that reminder?" question, scoped to a
    session and expiring; it is never persisted."""

    reminder_id: str
    label: str
    reminder_due: datetime
    day: datetime | None
    time_given: bool
    expires_at: datetime


@dataclass(frozen=True)
class AlarmWhen:
    due_at: datetime | None  # None: no usable time in the phrase
    day: datetime | None = None  # local date midnight when the phrase named a day


def _clock(text: str) -> tuple[int, int] | None:
    match = _TIME.search(text)
    if not match:
        return None
    if match["ap"]:
        hour, minute = int(match["h"]), int(match["m"] or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return None
        return hour % 12 + (12 if match["ap"].lower() == "pm" else 0), minute
    return int(match["h24"]), int(match["m24"])


def day_of(text: str, now: datetime, timezone: str) -> datetime | None:
    """Local midnight of a named day (today, tomorrow, a weekday), else None."""
    local = now.astimezone(ZoneInfo(timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
    lowered = text.lower()
    if re.search(r"\btomorrow\b", lowered):
        return local + timedelta(days=1)
    if re.search(r"\b(?:today|tonight)\b", lowered):
        return local
    for index, name in enumerate(_DAYS):
        if re.search(rf"\b{name}\b", lowered):
            return local + timedelta(days=(index - local.weekday()) % 7 or 7)
    return None


def parse_when(text: str, now: datetime, timezone: str, *, day: datetime | None = None) -> AlarmWhen:
    """`day` supplies a date already known from an earlier turn."""
    relative = _IN.search(text)
    if relative:
        unit = relative["unit"].lower()
        step = timedelta(minutes=1) if unit.startswith("m") else timedelta(hours=1)
        return AlarmWhen(now + int(relative["n"]) * step)
    named = day_of(text, now, timezone) or day
    clock = _clock(text)
    if clock is None:
        return AlarmWhen(None, named)
    local_now = now.astimezone(ZoneInfo(timezone))
    base = named or local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    due = base.replace(hour=clock[0], minute=clock[1])
    if named is None and due <= local_now:
        due += timedelta(days=1)
    return AlarmWhen(due, named)


def match_set(text: str) -> str | None:
    """The time phrase of "set an alarm for 7am" / "wake me at 7"; None when
    the text is not an alarm request (empty string: asked without a time)."""
    match = _SET.match(text)
    return match["rest"] if match else None


def is_alarm_query(text: str) -> bool:
    return bool(_ALARM_QUERY.search(text))


def classify_reply(text: str) -> str:
    """"no", "yes" or "other" for the reply to an alarm offer."""
    if _NO.match(text):
        return "no"
    if _YES.match(text) or _clock(text):
        return "yes"
    return "other"


def has_time(text: str) -> bool:
    return _clock(text) is not None or bool(_IN.search(text))


def format_alarm_when(due: datetime, timezone: str, now: datetime) -> str:
    local = due.astimezone(ZoneInfo(timezone))
    today = now.astimezone(ZoneInfo(timezone)).date()
    day = "today" if local.date() == today else "tomorrow" if local.date() == today + timedelta(days=1) else f"{local:%a %d %b}"
    return f"{local:%I:%M %p}".lstrip("0") + f" {day}"


def format_alarms_reply(alarms: list, timezone: str, now: datetime) -> str:
    live = [a for a in alarms if a.status == "scheduled"]
    if not live:
        return "You have no alarms set."
    return "Your alarms: " + "; ".join(f"{a.label} at {format_alarm_when(a.due_at, timezone, now)}" for a in live) + "."
