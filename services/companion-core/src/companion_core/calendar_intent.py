"""Placeholder intent detection for calendar queries — same honesty-about-
scope as privacy_classifier.py: a keyword matcher, not real NLU. Phase 10's
exit criterion ("'What's next?' works") needs the *answer* to be genuinely
computed from real calendar data, not that the question-understanding be
sophisticated; Phase 10+ reasoning replaces this matcher, not the contract
(a real CalendarEvent in, real formatted text out).
"""

from __future__ import annotations

from datetime import datetime

from companion_core.calendar.models import CalendarEvent

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


def format_today_schedule_reply(events: list[CalendarEvent]) -> str:
    """`events` must already be scoped to the caller's "today" window —
    this only formats, matching format_next_event_reply's split of
    concerns (real data in, real formatted text out)."""
    if not events:
        return "You have nothing on your calendar today."
    lines = [
        f"{event.start.strftime('%H:%M')} — {event.title}" + (f" at {event.location}" if event.location else "")
        for event in sorted(events, key=lambda event: event.start)
    ]
    return "Today's appointments:\n" + "\n".join(lines)


def today_window(now: datetime) -> tuple[datetime, datetime]:
    """Day boundaries in `now`'s own timezone (UTC for every other caller in
    this codebase — see calendar/reminders.py and app.py's next_event call).
    A local-timezone-aware owner setting would need this replaced, not
    patched, since every other calendar query here shares the same UTC
    assumption."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end
