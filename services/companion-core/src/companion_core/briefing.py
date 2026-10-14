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
    # Home (docs/phase-51.md): the sources added after Phase 18. Suggestions are model-generated and awaiting the owner; they never share a category with a confirmed record.
    PLANNER_REMINDER = "planner_reminder"
    SUGGESTION = "suggestion"
    WEATHER = "weather"


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
    BriefingCategory.PLANNER_REMINDER: 1,  # beside the calendar: both are things with a time today
    BriefingCategory.SUGGESTION: 5,
    BriefingCategory.WEATHER: 6,
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


# -- Home (docs/phase-51.md) ------------------------------------------------------------------------------------------------

def _hhmm(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%H:%M")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def home_items(home: dict) -> list[dict]:
    """The deterministic briefing lines for a Home snapshot (home.build_home), in the order they should be read. Pure: every word is composed from the snapshot's own fields.

    Each line says whether it is `confirmed` (the owner's own record or calendar), `pending_review` (a model-generated suggestion that is NOT a task, reminder or note until the owner accepts it),
    or `info` (weather, from the provider). Sections that are restricted, off or unavailable contribute a line only when the owner needs to know the picture is incomplete.
    """
    lines: list[dict] = []

    def add(category: BriefingCategory, status: str, text: str, ref: dict | None = None, urgency: Urgency = Urgency.NORMAL) -> None:
        lines.append({"category": category.value, "status": status, "text": text, "ref": ref, "urgency": urgency.value})

    schedule = home.get("schedule") or {}
    if schedule.get("status") in {"ok", "stale", "empty"}:
        for banner in schedule.get("all_day", []):
            add(BriefingCategory.CALENDAR, "confirmed", f"All day: {banner['title']}.", banner["ref"])
        timed = schedule.get("events", [])
        if timed:
            for e in timed:
                add(BriefingCategory.CALENDAR, "confirmed", f"{_hhmm(e['start'])}-{_hhmm(e['end'])}: {e['title']}.", e["ref"])
        elif not schedule.get("all_day"):
            add(BriefingCategory.CALENDAR, "confirmed", "Nothing on your calendar today.", {"screen": "calendar"}, Urgency.LOW)
        if schedule.get("status") == "stale":
            add(BriefingCategory.CALENDAR, "info", "The calendar may be out of date: the last sync is old.", {"screen": "calendar"})
    elif schedule.get("status") == "unavailable":
        add(BriefingCategory.CALENDAR, "info", "The calendar could not be read just now.", {"screen": "calendar"})

    reminders = home.get("reminders") or {}
    for r in reminders.get("overdue", []):
        add(BriefingCategory.PLANNER_REMINDER, "confirmed", f"Overdue reminder: {r['text']} (was due {_hhmm(r['due_at'])}).", r["ref"], Urgency.URGENT)
    for r in reminders.get("today", []):
        add(BriefingCategory.PLANNER_REMINDER, "confirmed", f"Reminder at {_hhmm(r['due_at'])}: {r['text']}.", r["ref"])
    upcoming = (reminders.get("counts") or {}).get("upcoming", 0)
    if upcoming:
        add(BriefingCategory.PLANNER_REMINDER, "confirmed", f"{_count(upcoming, 'more reminder')} in the next {reminders.get('upcoming_days', 7)} days.", {"screen": "reminders"}, Urgency.LOW)

    tasks = home.get("tasks") or {}
    if tasks.get("total"):
        extra = f", {tasks['from_meetings']} from meetings" if tasks.get("from_meetings") else ""
        add(BriefingCategory.TASK, "confirmed", f"{_count(tasks['total'], 'open task')}{extra} (tasks have no due dates).", {"screen": "tasks"}, Urgency.LOW)
        for t in tasks.get("items", [])[:3]:
            add(BriefingCategory.TASK, "confirmed", f"Open task: {t['text']}", t["ref"], Urgency.LOW)

    reviews = home.get("reviews") or {}
    notes = (reviews.get("note_proposals") or {}).get("count", 0)
    acts = (reviews.get("meeting_actions") or {}).get("count", 0)
    if notes:
        add(BriefingCategory.SUGGESTION, "pending_review", f"{_count(notes, 'note suggestion')} awaiting your review. They are not tasks or reminders until you accept them.", {"screen": "notes"}, Urgency.LOW)
    if acts:
        add(BriefingCategory.SUGGESTION, "pending_review", f"{_count(acts, 'meeting action candidate')} awaiting your review. They are not tasks until you confirm them.", {"screen": "meetings"}, Urgency.LOW)
    if reviews.get("status") in {"partial", "unavailable"}:
        add(BriefingCategory.SUGGESTION, "info", "The pending reviews could not be fully read just now.", None, Urgency.LOW)

    weather = home.get("weather") or {}
    if weather.get("status") in {"ok", "stale"}:
        now_ = weather["current"]
        today = weather["today"]
        parts = [f"{weather.get('location', 'Your area')}: {now_['summary'] or 'conditions unavailable'}"]
        if now_.get("temperature") is not None:
            parts[0] += f", {now_['temperature']:.0f}°C now"
        if today.get("high") is not None and today.get("low") is not None:
            parts.append(f"today {today['low']:.0f} to {today['high']:.0f}°C")
        if today.get("precipitation_total") is not None:
            rain = f"rain {today['precipitation_total']:.1f} mm"
            if today.get("precipitation_probability") is not None:
                rain += f", up to {today['precipitation_probability']:.0f}% chance"
            parts.append(rain)
        text = "; ".join(parts) + f" (Open-Meteo, observed {_hhmm(weather['observed_at'])})"
        if weather["status"] == "stale":
            text += ". This forecast is out of date"
        add(BriefingCategory.WEATHER, "info", text + ".", None, Urgency.LOW)
    return sorted(lines, key=lambda x: (_URGENCY_RANK[Urgency(x["urgency"])], _CATEGORY_ORDER[BriefingCategory(x["category"])]))
