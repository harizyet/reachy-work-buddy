"""Calendar storage. Read-only to the agent (docs/plan.md's Phase 10 row:
"Read-only next/list/free-busy first; later writes behind confirmation") —
`add_event` exists for operator/setup use (there's no external calendar
sync in this V0.1 default; see companion_core/calendar/postgres_store.py),
not as something the agent itself calls.

Single calendar, not scoped per user — matches the Telegram integration's
precedent (docs/plan.md: this is a personal assistant, not multi-tenant).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from companion_core.calendar.models import CalendarEvent


class CalendarStore(Protocol):
    async def add_event(self, event: CalendarEvent) -> CalendarEvent: ...
    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...
    async def next_event(self, after: datetime) -> CalendarEvent | None: ...


class InMemoryCalendarStore:
    def __init__(self) -> None:
        self._events: list[CalendarEvent] = []

    async def add_event(self, event: CalendarEvent) -> CalendarEvent:
        self._events.append(event)
        return event

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        # An event is in range if it overlaps [start, end) at all, not just
        # if it starts inside the window — a meeting that started before
        # `start` and runs past it is still relevant to "am I free then".
        overlapping = [e for e in self._events if e.start < end and e.end > start]
        return sorted(overlapping, key=lambda e: e.start)

    async def next_event(self, after: datetime) -> CalendarEvent | None:
        upcoming = sorted((e for e in self._events if e.start >= after), key=lambda e: e.start)
        return upcoming[0] if upcoming else None
