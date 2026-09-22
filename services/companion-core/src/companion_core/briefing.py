"""Daily briefing: combines calendar/tasks/email/reminders/project events
into one prioritized list. See docs/adr/0015-daily-briefing.md.

Pure composition over the four stores Phase 10-12/14 already built — no new
storage, no background scheduler (same "callable on demand" discipline as
calendar/reminders.py). reachy-hub's POST /briefing/{user_id} is the one
caller: it fetches this list, has Reachy perform an arrival greeting
gesture, then routes the detailed text through the exact same
resolve_delivery_channel/apply_privacy_override/decide_action pipeline
check_reminders (Phase 17) uses.

`BriefingItem` lives here, not shared/models — same ADR 0001 reasoning as
`ReminderPayload` (app.py): reachy-hub only ever relays opaque JSON.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel

from companion_core.calendar.reminders import due_reminders, reminder_urgency
from companion_core.calendar.store import CalendarStore
from companion_core.email.store import EmailStore
from companion_core.memory.store import MemoryStore
from companion_core.tasks.models import TaskStatus
from companion_core.tasks.store import TaskStore
from shared.models.memory import MemoryType
from shared.models.response import Privacy, Urgency

# How far ahead/back each category looks. Not user-configurable (no
# exit criterion asks for that) — chosen to keep the briefing to "today
# and what just happened", not a full history dump.
_CALENDAR_LOOKAHEAD_HOURS = 24
_EMAIL_LOOKBACK_HOURS = 24
_PROJECT_LOOKBACK_HOURS = 48


class BriefingCategory(StrEnum):
    REMINDER = "reminder"
    CALENDAR = "calendar"
    TASK = "task"
    EMAIL = "email"
    PROJECT = "project"


class BriefingItem(BaseModel):
    category: BriefingCategory
    text: str
    privacy: Privacy
    urgency: Urgency


# Tie-break order when urgency is equal: reminders (imminent) lead, project
# context (least time-bound) trails. Matches docs/plan.md's own listed
# input order (calendar/tasks/email/reminders/project events) with reminders
# pulled to the front since they're the one category that's already
# urgency-graded for "starting very soon".
_CATEGORY_ORDER = {
    BriefingCategory.REMINDER: 0,
    BriefingCategory.CALENDAR: 1,
    BriefingCategory.TASK: 2,
    BriefingCategory.EMAIL: 3,
    BriefingCategory.PROJECT: 4,
}
_URGENCY_RANK = {Urgency.URGENT: 0, Urgency.NORMAL: 1, Urgency.LOW: 2}


def _prioritize(items: list[BriefingItem]) -> list[BriefingItem]:
    return sorted(items, key=lambda item: (_URGENCY_RANK[item.urgency], _CATEGORY_ORDER[item.category]))


async def build_briefing(
    *,
    calendar_store: CalendarStore,
    task_store: TaskStore,
    email_store: EmailStore,
    memory_store: MemoryStore,
    now: datetime,
) -> list[BriefingItem]:
    items: list[BriefingItem] = []

    # Reminders: events starting imminently (reuses Phase 10's due_reminders
    # query and Phase 17's urgency grading verbatim — no duplicated logic).
    for event in await due_reminders(calendar_store, now, within_minutes=15):
        items.append(
            BriefingItem(
                category=BriefingCategory.REMINDER,
                text=f"Reminder: '{event.title}' starts at {event.start.strftime('%H:%M')}.",
                privacy=Privacy.WORK_PRIVATE,
                urgency=reminder_urgency(event, now),
            )
        )

    # Calendar: the day's whole schedule, deliberately overlapping with the
    # reminders above (an imminent event legitimately appears twice: once as
    # an urgent reminder, once as part of the day's shape) rather than
    # de-duplicating — see docs/adr/0015.
    horizon = now + timedelta(hours=_CALENDAR_LOOKAHEAD_HOURS)
    for event in await calendar_store.list_events(now, horizon):
        items.append(
            BriefingItem(
                category=BriefingCategory.CALENDAR,
                text=f"'{event.title}' at {event.start.strftime('%H:%M')}-{event.end.strftime('%H:%M')}.",
                privacy=Privacy.WORK_PRIVATE,
                urgency=Urgency.NORMAL,
            )
        )

    # Tasks: open follow-ups (Phase 11). No due dates on Task (models.py),
    # so these are informational, not time-graded.
    for task in await task_store.list_tasks(TaskStatus.OPEN):
        items.append(
            BriefingItem(
                category=BriefingCategory.TASK,
                text=f"Open task: {task.text}",
                privacy=Privacy.WORK_PRIVATE,
                urgency=Urgency.LOW,
            )
        )

    # Email: recently received. EmailMessage (email/models.py) has no
    # read/unread flag — there's no real inbox sync in this V0.1 default —
    # so "received recently" is the honest stand-in for "unread".
    email_cutoff = now - timedelta(hours=_EMAIL_LOOKBACK_HOURS)
    for message in await email_store.list_received():
        if message.received_at >= email_cutoff:
            items.append(
                BriefingItem(
                    category=BriefingCategory.EMAIL,
                    text=f"Email from {message.sender}: {message.subject}",
                    privacy=Privacy.WORK_PRIVATE,
                    urgency=Urgency.LOW,
                )
            )

    # Project events: this codebase has no dedicated "project events" store
    # — docs/plan.md names it as an input to combine, not a phase of its
    # own — so recent episodic memory tagged with a project_scope (Phase 12)
    # is the honest existing source, same scope-to-what-actually-exists
    # discipline ADR 0014 used for "presence".
    project_cutoff = now - timedelta(hours=_PROJECT_LOOKBACK_HOURS)
    for record in await memory_store.list_memories(MemoryType.EPISODIC):
        if record.project_scope is not None and record.created_at >= project_cutoff:
            items.append(
                BriefingItem(
                    category=BriefingCategory.PROJECT,
                    text=f"[{record.project_scope}] {record.content}",
                    privacy=record.sensitivity,
                    urgency=Urgency.LOW,
                )
            )

    return _prioritize(items)
