"""Computing which events are due for a reminder right now.

Deliberately not a background scheduler/poller — that's proactive-
notification infrastructure (queueing, push) that docs/plan.md scopes to
Phases 17-18, not Phase 10. This is a pure query, callable on demand
(reachy-hub's /calendar/check-reminders calls it), which is enough to prove
"meeting reminders route appropriately" (Phase 10's exit criterion) without
inventing a scheduler this phase doesn't need.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from companion_core.calendar.models import CalendarEvent
from companion_core.calendar.store import CalendarStore


async def due_reminders(store: CalendarStore, now: datetime, within_minutes: int) -> list[CalendarEvent]:
    window_end = now + timedelta(minutes=within_minutes)
    # list_events returns anything *overlapping* the window, including
    # meetings already in progress; a reminder is only useful for events
    # that haven't started yet.
    candidates = await store.list_events(now, window_end)
    return [event for event in candidates if now <= event.start <= window_end]
