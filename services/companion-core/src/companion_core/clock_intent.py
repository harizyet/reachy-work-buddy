"""Deterministic time and date answers from the clock, in the owner's
timezone. Owner decision (2026-09-26, 24e physical run): a question about
the local time is answered from the clock, never searched or left to the
model; a time question that names another place ("What time is it in
Tokyo?") searches instead (websearch/policy.py).
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

_TIME_RE = re.compile(
    r"\b(?:what(?:'s| is) the (?:current |exact )?time"
    r"|what time is it|what time it is"
    r"|(?:tell|give) me the time|(?:got|have) the time|current time)\b"
)
_DATE_RE = re.compile(
    r"\b(?:what(?:'s| is) (?:the |today's )?date|what date is it|what date it is"
    r"|what day is (?:it|today)|what day it is|which day is (?:it|today))\b"
)
# Words that may follow the question without changing it. Anything else
# ("What's the time difference…", "What's the date of the election?") is
# not a clock question and goes through the normal path.
_FILLER = frozenset({
    "now", "right", "currently", "today", "please", "reachy", "exactly", "again",
    "then", "here", "at", "the", "moment", "minute", "for", "me", "us", "where", "we", "are",
})
# "in Tokyo" names a place; "here" and "at the moment" do not.
_PLACE_RE = re.compile(r"\b(?:in|at|for)\s+(?:the\s+)?([\w'-]+)")
_LOCAL_PLACES = frozenset({"here", "home", "moment", "minute", "me", "us", "now"})


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[\w']+", text.lower()))


def _classify(text: str) -> tuple[str, bool] | None:
    """(kind, names_place) for a time or date question, else None."""
    normalized = _normalize(text)
    for kind, pattern in (("time", _TIME_RE), ("date", _DATE_RE)):
        match = pattern.search(normalized)
        if match is None:
            continue
        rest = normalized[match.end():]
        place = _PLACE_RE.search(rest)
        if place is not None and place.group(1) not in _LOCAL_PLACES:
            return kind, True
        if set(rest.split()) <= _FILLER:
            return kind, False
    return None


def is_remote_time_query(text: str) -> bool:
    """A time or date question about another place, which needs a search."""
    found = _classify(text)
    return found is not None and found[1]


def match_local_clock(text: str) -> str | None:
    """"time" or "date" for a question about the owner's own clock, else None."""
    found = _classify(text)
    return found[0] if found is not None and not found[1] else None


def format_clock_reply(kind: str, now: datetime, timezone: str) -> str:
    local = now.astimezone(ZoneInfo(timezone))
    if kind == "time":
        hour = local.hour % 12 or 12
        return f"It's {hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}."
    return f"It's {local.strftime('%A')}, {local.day} {local.strftime('%B %Y')}."
