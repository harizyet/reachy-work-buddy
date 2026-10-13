"""Placeholder intent detection for calendar queries — same honesty-about-
scope as privacy_classifier.py: a keyword matcher, not real NLU. Phase 10's
exit criterion ("'What's next?' works") needs the *answer* to be genuinely
computed from real calendar data, not that the question-understanding be
sophisticated; Phase 10+ reasoning replaces this matcher, not the contract
(a real CalendarEvent in, real formatted text out).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from companion_core.calendar.models import CalendarEvent
from companion_core.task_intent import time_scope

_NEXT_EVENT_PHRASES = ("what's next", "whats next", "next meeting", "next event", "what do i have next")

_TODAY_SCHEDULE_PHRASES = (
    "appointments today", "my appointments today", "appointments do i have today",
    "what's on my calendar today", "whats on my calendar today",
    "today's schedule", "todays schedule", "my schedule today",
    "what do i have today", "today's agenda", "todays agenda", "agenda today",
)


def is_next_event_query(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _NEXT_EVENT_PHRASES)


def is_today_schedule_query(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _TODAY_SCHEDULE_PHRASES)


def format_next_event_reply(event: CalendarEvent | None) -> str:
    if event is None:
        return "You have nothing else on your calendar."
    when = event.start.strftime("%A %H:%M")
    location = f" at {event.location}" if event.location else ""
    return f"Your next event is '{event.title}' on {when}{location}."


def _local(moment: datetime, tz: str | None) -> datetime:
    return moment.astimezone(ZoneInfo(tz)) if tz else moment


def _line(event: CalendarEvent, tz: str | None) -> str:
    start, end = _local(event.start, tz), _local(event.end, tz)
    where = f" at {event.location}" if event.location else ""
    flag = " (tentative)" if event.status == "tentative" else ""
    if event.all_day:
        return f"{event.title}{_days(event, tz)}{flag}"
    span = f"{start:%H:%M}" if end <= start else f"{start:%H:%M}–{end:%H:%M}"
    return f"{span} — {event.title}{where}{flag}"


def _days(event: CalendarEvent, tz: str | None) -> str:
    """The days an all-day event covers. Its end is exclusive (the day after the last one), so a three-day leave from the 19th ends on the 21st."""
    first, last = _local(event.start, tz), _local(event.end, tz) - timedelta(days=1)
    if last.date() <= first.date():
        return ""
    return f" ({first:%a %d %b} to {last:%a %d %b})"


def _attending(events: list[CalendarEvent]) -> list[CalendarEvent]:
    return sorted((e for e in events if e.status != "cancelled" and e.response != "declined"), key=lambda e: e.start)


_SECTIONS = (
    ("Meetings", "meeting"), ("Appointments", "personal_appointment"), ("Other timed events", "unknown_timed"), ("Busy (details hidden)", "busy_private"),
    ("Leave", "leave_or_ooo"), ("All day", "all_day"),
)


def format_today_schedule_reply(events: list[CalendarEvent], tz: str | None = None) -> str:
    """`events` must already be scoped to the caller's "today" window — this only formats, matching format_next_event_reply's split of concerns (real data in, real formatted text out).

    Events that have been through the classifier are grouped so a meeting, an appointment and a leave day cannot be mistaken for one another; an event that has not (a local one) is listed as before.
    """
    events = _attending(events)
    if not events:
        return "You have nothing on your calendar today."
    if all(e.classification is None for e in events):
        lines = [f"{event.start.strftime('%H:%M')} — {event.title}" + (f" at {event.location}" if event.location else "") for event in events]
        return "Today's appointments:\n" + "\n".join(lines)
    blocks = []
    for heading, name in _SECTIONS:
        group = [e for e in events if (e.classification or "unknown_timed") == name]
        if group:
            blocks.append(f"{heading}:\n" + "\n".join(f"- {_line(e, tz)}" for e in group))
    return "On your calendar today:\n" + "\n".join(blocks)


# --- "Do I have meetings tomorrow?" and "Am I on leave next week?" ------------------------------------------------------------------------------------------

_OPENER = r"^\W*(?:do i have|have i got|am i|are there|is there|what|which|how many|any|show|list|tell me|got any|check|will i|are we|when)\b"
_NOT_A_LOOKUP = re.compile(r"\b(?:notes?|transcripts?|recordings?|summar\w+|minutes|analy\w+|record|start|join|schedule a|set up|book|cancel|delete|apply|request|submit)\b", re.IGNORECASE)
_MEETINGS = re.compile(_OPENER + r".*\bmeetings?\b", re.IGNORECASE)
_LEAVE = re.compile(
    _OPENER + r".*\b(?:on leave|annual leave|sick leave|any leave|my leave|leave (?:this|next|today|tomorrow)|out of office|ooo|on holiday|on vacation|time off|days? off|off work)\b",
    re.IGNORECASE,
)


def is_meetings_query(text: str) -> bool:
    """A question about the owner's meetings in a named time ("tomorrow", "next week"). Without a time it is not claimed: "Which meetings mention the review?" is a records question."""
    lowered = text.strip().lower()
    scope = time_scope(lowered)
    return bool(_MEETINGS.search(lowered)) and not _NOT_A_LOOKUP.search(lowered) and (scope.window is not None or scope.problem is not None)


def is_leave_query(text: str) -> bool:
    lowered = text.strip().lower()
    return bool(_LEAVE.search(lowered)) and not _NOT_A_LOOKUP.search(lowered)


@dataclass(frozen=True)
class QueryWindow:
    start: datetime | None
    end: datetime | None
    label: str  # "today", "tomorrow", "this week", "next week"
    problem: str | None = None  # a fixed reply when the wording names a window this does not read


_WINDOW_LIMIT = "I can only look at today, tomorrow, this week or next week, so I haven't checked your calendar for that. Ask about one of those."
_WINDOW_AMBIGUOUS = "That names more than one time range, so I haven't picked one. Ask about just one of today, tomorrow, this week or next week."


def query_window(text: str, now: datetime, tz: str, *, default_days: int | None = None) -> QueryWindow:
    """Whole days in the owner's timezone. With no window named, `default_days` days from today (or None for a window the caller must name)."""
    scope = time_scope(text)
    if scope.problem == "unsupported":
        return QueryWindow(None, None, "", _WINDOW_LIMIT)
    if scope.problem == "ambiguous":
        return QueryWindow(None, None, "", _WINDOW_AMBIGUOUS)
    today = now.astimezone(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    if scope.window == "tomorrow":
        return QueryWindow(today + timedelta(days=1), today + timedelta(days=2), "tomorrow")
    if scope.window == "this_week":
        return QueryWindow(today, monday + timedelta(days=7), "this week")
    if scope.window == "next_week":
        return QueryWindow(monday + timedelta(days=7), monday + timedelta(days=14), "next week")
    if scope.window == "today" or default_days is None:
        return QueryWindow(today, today + timedelta(days=1), "today")
    return QueryWindow(today, today + timedelta(days=default_days), f"in the next {default_days} days")


def format_meetings_reply(events: list[CalendarEvent], label: str, tz: str | None = None) -> str:
    """Only events classified as meetings. Timed events that could not be classified are not guessed at; they are counted so the answer does not claim more than it knows."""
    attending = _attending(events)
    meetings = [e for e in attending if e.classification == "meeting"]
    unsure = len([e for e in attending if e.classification == "unknown_timed"])
    if meetings:
        body = f"You have {len(meetings)} meeting{'s' if len(meetings) != 1 else ''} {label}:\n" + "\n".join(f"- {_dated(e, tz, label)}" for e in meetings)
    else:
        body = f"You have no meetings {label}."
    if unsure:
        body += f"\n({unsure} other timed event{'s' if unsure != 1 else ''} I couldn't tell was a meeting {'is' if unsure == 1 else 'are'} not counted.)"
    return body


def _dated(event: CalendarEvent, tz: str | None, label: str) -> str:
    line = _line(event, tz)
    return line if label in ("today", "tomorrow") else f"{_local(event.start, tz):%a %d %b} {line}"


def format_leave_reply(events: list[CalendarEvent], label: str, tz: str | None = None) -> str:
    """Leave periods that overlap the window, with their real dates (a multi-day leave shows its whole span, not just the part inside the window)."""
    leave = [e for e in _attending(events) if e.classification == "leave_or_ooo"]
    if not leave:
        return f"No leave is marked on your calendar {label}."
    lines = []
    for event in leave:
        if event.all_day:
            first, last = _local(event.start, tz), _local(event.end, tz) - timedelta(days=1)
            when = f"{first:%a %d %b}" if last.date() <= first.date() else f"{first:%a %d %b} to {last:%a %d %b}"
        else:
            start, end = _local(event.start, tz), _local(event.end, tz)
            when = f"{start:%a %d %b %H:%M}–{end:%H:%M}"
        lines.append(f"- {event.title}: {when}")
    return f"Yes, you're on leave {label}:\n" + "\n".join(lines)


def today_window(now: datetime) -> tuple[datetime, datetime]:
    """Day boundaries in `now`'s own timezone (UTC for every other caller in
    this codebase — see calendar/reminders.py and app.py's next_event call).
    A local-timezone-aware owner setting would need this replaced, not
    patched, since every other calendar query here shares the same UTC
    assumption."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end
