"""No pytest-asyncio/anyio plugin is installed anywhere else in this
codebase, so `async def test_...` would silently no-op rather than fail —
wrapping each test body in asyncio.run keeps these genuinely sync test
functions, consistent with everything else here (see test_calendar_store.py)."""

import asyncio
from datetime import UTC, datetime, timedelta

from companion_core.briefing import BriefingCategory, build_briefing
from companion_core.calendar.models import CalendarEvent
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.tasks.store import InMemoryTaskStore

from shared.models.memory import MemoryType
from shared.models.response import Privacy, Urgency

NOW = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _stores() -> tuple[InMemoryCalendarStore, InMemoryTaskStore, InMemoryEmailStore, InMemoryMemoryStore]:
    return InMemoryCalendarStore(), InMemoryTaskStore(), InMemoryEmailStore(), InMemoryMemoryStore()


def test_empty_briefing_when_nothing_is_going_on() -> None:
    async def run() -> None:
        calendar, tasks, email, memory = _stores()
        items = await build_briefing(
            calendar_store=calendar, task_store=tasks, email_store=email, memory_store=memory, now=NOW
        )
        assert items == []

    asyncio.run(run())


def test_imminent_event_appears_as_both_reminder_and_calendar_item() -> None:
    """Deliberate overlap (docs/adr/0015): a reminder is a subset of the
    day's calendar, not a separate source, so the same event legitimately
    shows up twice — once urgency-graded, once as part of the day's shape."""

    async def run() -> None:
        calendar, tasks, email, memory = _stores()
        await calendar.add_event(
            CalendarEvent(title="Standup", start=NOW + timedelta(minutes=3), end=NOW + timedelta(minutes=18))
        )
        items = await build_briefing(
            calendar_store=calendar, task_store=tasks, email_store=email, memory_store=memory, now=NOW
        )
        categories = {item.category for item in items}
        assert categories == {BriefingCategory.REMINDER, BriefingCategory.CALENDAR}
        reminder = next(i for i in items if i.category == BriefingCategory.REMINDER)
        assert reminder.urgency == Urgency.URGENT  # within 5 minutes

    asyncio.run(run())


def test_open_tasks_are_included_done_tasks_are_not() -> None:
    async def run() -> None:
        calendar, tasks, email, memory = _stores()
        open_task = await tasks.add_task("write the ADR")
        done_task = await tasks.add_task("send the email")
        await tasks.complete_task(done_task.id)

        items = await build_briefing(
            calendar_store=calendar, task_store=tasks, email_store=email, memory_store=memory, now=NOW
        )
        assert len(items) == 1
        assert items[0].category == BriefingCategory.TASK
        assert open_task.text in items[0].text

    asyncio.run(run())


def test_only_recent_email_is_included() -> None:
    async def run() -> None:
        calendar, tasks, email, memory = _stores()
        recent = await email.add_received(sender="a@x.com", subject="Recent", body="hi")
        recent.received_at = NOW - timedelta(hours=1)
        stale = await email.add_received(sender="b@x.com", subject="Stale", body="old")
        stale.received_at = NOW - timedelta(hours=48)

        items = await build_briefing(
            calendar_store=calendar, task_store=tasks, email_store=email, memory_store=memory, now=NOW
        )
        email_items = [i for i in items if i.category == BriefingCategory.EMAIL]
        assert len(email_items) == 1
        assert "Recent" in email_items[0].text

    asyncio.run(run())


def test_only_project_scoped_recent_episodic_memory_is_included() -> None:
    async def run() -> None:
        calendar, tasks, email, memory = _stores()
        scoped = await memory.add_memory(
            content="shipped the migration", source="test", type=MemoryType.EPISODIC, project_scope="Falcon"
        )
        scoped.created_at = NOW - timedelta(hours=2)
        await memory.add_memory(content="no project here", source="test", type=MemoryType.EPISODIC)
        old = await memory.add_memory(
            content="ancient project note", source="test", type=MemoryType.EPISODIC, project_scope="Falcon"
        )
        old.created_at = NOW - timedelta(hours=72)
        await memory.add_memory(
            content="a profile fact", source="test", type=MemoryType.PROFILE, project_scope="Falcon"
        )

        items = await build_briefing(
            calendar_store=calendar, task_store=tasks, email_store=email, memory_store=memory, now=NOW
        )
        project_items = [i for i in items if i.category == BriefingCategory.PROJECT]
        assert len(project_items) == 1
        assert "Falcon" in project_items[0].text
        assert "shipped the migration" in project_items[0].text

    asyncio.run(run())


def test_items_are_prioritized_urgent_first_then_category_order() -> None:
    async def run() -> None:
        calendar, tasks, email, memory = _stores()
        await tasks.add_task("low priority housekeeping")
        await calendar.add_event(
            CalendarEvent(title="Kickoff", start=NOW + timedelta(minutes=2), end=NOW + timedelta(minutes=30))
        )
        received = await email.add_received(sender="a@x.com", subject="FYI", body="hi")
        received.received_at = NOW

        items = await build_briefing(
            calendar_store=calendar, task_store=tasks, email_store=email, memory_store=memory, now=NOW
        )
        assert [i.category for i in items] == [
            BriefingCategory.REMINDER,
            BriefingCategory.CALENDAR,
            BriefingCategory.TASK,
            BriefingCategory.EMAIL,
        ]
        assert items[0].urgency == Urgency.URGENT
        assert items[0].privacy == Privacy.WORK_PRIVATE

    asyncio.run(run())
