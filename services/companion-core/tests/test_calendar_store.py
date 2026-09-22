"""No pytest-asyncio/anyio-plugin is installed anywhere else in this
codebase, so `async def test_...` would silently no-op rather than fail
(pytest just discards the unawaited coroutine). Wrapping each test body in
asyncio.run keeps these genuinely sync test functions, consistent with
everything else here."""

import asyncio
from datetime import UTC, datetime, timedelta

from companion_core.calendar.models import CalendarEvent
from companion_core.calendar.reminders import due_reminders
from companion_core.calendar.store import InMemoryCalendarStore


def _event(title: str, start: datetime, minutes: int = 30) -> CalendarEvent:
    return CalendarEvent(title=title, start=start, end=start + timedelta(minutes=minutes))


def test_next_event_returns_earliest_upcoming() -> None:
    async def run() -> None:
        store = InMemoryCalendarStore()
        now = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        await store.add_event(_event("Later", now + timedelta(hours=2)))
        await store.add_event(_event("Sooner", now + timedelta(hours=1)))

        event = await store.next_event(now)
        assert event.title == "Sooner"

    asyncio.run(run())


def test_next_event_ignores_past_events() -> None:
    async def run() -> None:
        store = InMemoryCalendarStore()
        now = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        await store.add_event(_event("Yesterday", now - timedelta(days=1)))
        assert await store.next_event(now) is None

    asyncio.run(run())


def test_list_events_includes_overlapping_not_just_starting_in_range() -> None:
    async def run() -> None:
        store = InMemoryCalendarStore()
        now = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        # Starts before the query window, ends inside it.
        await store.add_event(_event("Spanning", now - timedelta(minutes=15), minutes=30))

        events = await store.list_events(now, now + timedelta(hours=1))
        assert [e.title for e in events] == ["Spanning"]

    asyncio.run(run())


def test_due_reminders_only_includes_events_starting_within_the_window() -> None:
    async def run() -> None:
        store = InMemoryCalendarStore()
        now = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        await store.add_event(_event("Soon", now + timedelta(minutes=10)))
        await store.add_event(_event("Later", now + timedelta(minutes=45)))
        await store.add_event(_event("InProgress", now - timedelta(minutes=10), minutes=30))

        due = await due_reminders(store, now, within_minutes=15)
        assert [e.title for e in due] == ["Soon"]

    asyncio.run(run())
