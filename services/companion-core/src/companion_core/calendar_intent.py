"""Placeholder intent detection for calendar queries — same honesty-about-
scope as privacy_classifier.py: a keyword matcher, not real NLU. Phase 10's
exit criterion ("'What's next?' works") needs the *answer* to be genuinely
computed from real calendar data, not that the question-understanding be
sophisticated; Phase 10+ reasoning replaces this matcher, not the contract
(a real CalendarEvent in, real formatted text out).
"""

from __future__ import annotations

from companion_core.calendar.models import CalendarEvent

_NEXT_EVENT_PHRASES = ("what's next", "whats next", "next meeting", "next event", "what do i have next")


def is_next_event_query(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _NEXT_EVENT_PHRASES)


def format_next_event_reply(event: CalendarEvent | None) -> str:
    if event is None:
        return "You have nothing else on your calendar."
    when = event.start.strftime("%A %H:%M")
    location = f" at {event.location}" if event.location else ""
    return f"Your next event is '{event.title}' on {when}{location}."
