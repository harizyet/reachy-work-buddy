"""The Home snapshot (docs/phase-51.md): what is on the owner's plate today, composed from the stores that already exist.

Read-only and on demand, like briefing.py (ADR 0015): nothing here writes, accepts, schedules or calls a model. Each section is built on its own, so one failing source marks only its own
section. The caller's AccessContext (the sensitivity ceiling the hub established, never a request field) is applied to every record BEFORE anything is counted or summarised, so a record the
caller may not read changes neither a list nor a count; at the public ceiling no section reports anything at all, not even that records exist.

What is confirmed and what is only suggested stays separate: tasks and reminders are the owner's records; note proposals and meeting action candidates are model-generated suggestions awaiting
review and are labelled so wherever they appear. A meeting action the owner confirmed IS a task, listed once in the tasks section with its origin; it never also appears as a suggestion.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from companion_core.calendar.classify import EventClass
from companion_core.calendar.feed import FeedCalendar
from companion_core.calendar.models import CalendarEvent
from companion_core.meeting_analysis.models import ItemKind, ItemStatus
from companion_core.notepad_processing.models import ProposalStatus
from companion_core.planner.models import ReminderStatus
from companion_core.semantic import access as rules
from companion_core.semantic.model import AccessContext
from companion_core.tasks.models import TaskStatus
from shared.models.response import Privacy
from shared.protocols.home_api import SECTIONS

log = logging.getLogger(__name__)

TASK_LIMIT = 8
REMINDER_LIMIT = 6
REVIEW_LIMIT = 5
UPCOMING_DAYS = 7
TEXT_LIMIT = 200
_BUSY = "Busy"
_ALL_DAY_KINDS = {EventClass.LEAVE_OR_OOO.value, EventClass.ALL_DAY.value}


def _clip(text: str, limit: int = TEXT_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def readable(access: AccessContext, sensitivity: Privacy, project_scope: str | None = None) -> bool:
    return rules.within_ceiling(sensitivity, access.sensitivity_ceiling) and rules.scope_permits(access, project_scope)


# -- schedule -----------------------------------------------------------------------------------------------------------------

def event_view(event: CalendarEvent, zone: ZoneInfo) -> dict:
    """The fields a Home card may show. The text is the event's own title: a hidden or Busy-only event shows "Busy" and nothing else, and no description, attendee or notes exist in
    this view to be invented."""
    hidden = event.redacted or event.classification == EventClass.BUSY_PRIVATE.value
    return {
        "id": event.id, "event_key": event.event_key, "title": _BUSY if hidden else _clip(event.title, 120), "start": event.start.astimezone(zone).isoformat(), "end": event.end.astimezone(zone).isoformat(),
        "all_day": event.all_day, "classification": event.classification, "location": None if hidden or not event.location else _clip(event.location, 80),
        "status": event.status, "response": event.response, "redacted": event.redacted, "recurring": event.recurring, "remind": event.remind,
        "ref": {"screen": "calendar", "id": event.event_key or event.id},
    }


def _on_schedule(event: CalendarEvent) -> bool:
    return event.status != "cancelled" and event.response != "declined"


async def _schedule(*, calendar_store, now: datetime, zone: ZoneInfo, **_) -> dict:
    today = now.astimezone(zone).date()
    start = datetime.combine(today, datetime.min.time(), zone)
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), zone)
    generation, revision, feed = None, None, None
    if isinstance(calendar_store, FeedCalendar):
        snapshot = await calendar_store.schedule(start, end)  # events and feed status from ONE revision
        events, generation, revision, feed = snapshot["events"], snapshot["generation"], snapshot["snapshot_revision"], snapshot["feed"]
    else:
        events = await calendar_store.list_events(start, end)
    events = [e for e in events if _on_schedule(e)]
    timed = [e for e in events if not e.all_day and e.classification not in _ALL_DAY_KINDS]
    banners = [e for e in events if e not in timed]
    upcoming = await calendar_store.next_event(now)
    out = {
        "status": "ok" if events else "empty", "date": today.isoformat(), "timezone": str(zone.key),
        "generation": generation, "snapshot_revision": revision,
        "feed": None if feed is None else {k: feed.get(k) for k in ("configured", "freshness", "sync_state", "last_success_at", "age_seconds", "error")},
        "events": [event_view(e, zone) for e in timed], "all_day": [event_view(e, zone) for e in banners],
        "on_leave": any(e.classification == EventClass.LEAVE_OR_OOO.value for e in banners),
        "next_event": None if upcoming is None or not _on_schedule(upcoming) else event_view(upcoming, zone),
        "counts": {"timed": len(timed), "all_day": len(banners)},
    }
    if feed is not None and feed.get("freshness") == "stale":
        out["status"] = "stale" if events else out["status"]
    out["feed_configured"] = None if feed is None else bool(feed.get("configured"))
    return out


# -- tasks --------------------------------------------------------------------------------------------------------------------

async def _tasks(*, access, task_store, notepad_service, analysis_service, **_) -> dict:
    open_tasks = [t for t in await task_store.list_tasks(TaskStatus.OPEN) if readable(access, t.sensitivity, t.project_scope)]
    ids = [t.id for t in open_tasks]
    # Where a task came from, read from the records that confirmed it: a meeting action the owner accepted IS this task (one row, never a second entry), a note proposal likewise.
    meeting_origin: dict[str, dict] = {}
    if analysis_service is not None and ids:
        accepted = {i.record_id: i for i in await analysis_service.store.list_items(statuses=(ItemStatus.ACCEPTED,)) if i.record_id in set(ids)}
        for record_id, item in accepted.items():
            meeting = await analysis_service.meetings.get_meeting(item.meeting_id)
            meeting_origin[record_id] = {"kind": "meeting", "meeting_id": item.meeting_id, "meeting_title": meeting.title if meeting else None}
    note_origin: dict[str, dict] = {}
    if notepad_service is not None and ids:
        for p in await notepad_service.store.list_provenance(ids):
            note = await notepad_service.planner.get_note(p.note_id)
            note_origin[p.record_id] = {"kind": "note", "note_id": p.note_id, "note_title": note.title if note else None}
    items = [{
        "id": t.id, "text": _clip(t.text), "created_at": t.created_at.isoformat(), "origin": meeting_origin.get(t.id) or note_origin.get(t.id),
        "ref": {"screen": "tasks", "id": t.id},
    } for t in sorted(open_tasks, key=lambda t: t.created_at, reverse=True)[:TASK_LIMIT]]
    return {
        "status": "ok" if open_tasks else "empty", "total": len(open_tasks), "shown": len(items), "has_due_dates": False,  # a task has no due date (schema 029): none is shown or implied
        "from_meetings": sum(1 for t in open_tasks if t.id in meeting_origin), "from_notes": sum(1 for t in open_tasks if t.id in note_origin), "items": items,
    }


# -- reminders ----------------------------------------------------------------------------------------------------------------

async def _reminders(*, access, planner_store, now: datetime, zone: ZoneInfo, **_) -> dict:
    pending = [r for r in await planner_store.list_reminders() if r.status == ReminderStatus.PENDING and readable(access, r.sensitivity)]
    today = now.astimezone(zone).date()
    horizon = today + timedelta(days=UPCOMING_DAYS)

    def view(r) -> dict:
        return {"id": r.id, "text": _clip(r.text), "due_at": r.due_at.astimezone(zone).isoformat(), "ref": {"screen": "reminders", "id": r.id}}

    overdue = [r for r in pending if r.due_at < now and r.due_at.astimezone(zone).date() <= today]
    due_today = [r for r in pending if r.due_at >= now and r.due_at.astimezone(zone).date() == today]
    upcoming = [r for r in pending if today < r.due_at.astimezone(zone).date() <= horizon]
    return {
        "status": "ok" if (overdue or due_today or upcoming) else "empty", "upcoming_days": UPCOMING_DAYS,
        "counts": {"overdue": len(overdue), "today": len(due_today), "upcoming": len(upcoming)},
        "overdue": [view(r) for r in overdue[:REMINDER_LIMIT]], "today": [view(r) for r in due_today[:REMINDER_LIMIT]], "upcoming": [view(r) for r in upcoming[:REMINDER_LIMIT]],
    }


# -- reviews: suggestions awaiting the owner ----------------------------------------------------------------------------------

async def _note_proposals(access, service) -> dict:
    if service is None:
        return {"status": "off", "count": 0, "items": []}
    rows = [p for p in await service.store.list_proposals(statuses=(ProposalStatus.PENDING,)) if readable(access, p.sensitivity, p.project_scope)]
    items, titles = [], {}
    for p in rows[:REVIEW_LIMIT]:
        note_id = (list(p.associations) or [p.note_id])[0]
        if note_id not in titles:
            note = await service.planner.get_note(note_id)
            titles[note_id] = note.title if note else None
        items.append({"id": p.id, "kind": p.kind.value, "text": _clip(p.text), "note_id": note_id, "note_title": titles[note_id], "pending_review": True, "ref": {"screen": "notes", "id": note_id}})
    return {"status": "ok" if rows else "empty", "count": len(rows), "items": items}


async def _meeting_actions(access, service) -> dict:
    if service is None:
        return {"status": "off", "count": 0, "items": []}
    rows = [i for i in await service.store.list_items(statuses=(ItemStatus.PENDING,)) if i.kind is ItemKind.ACTION and readable(access, i.sensitivity, i.project_scope)]
    items, titles = [], {}
    for i in rows[:REVIEW_LIMIT]:
        if i.meeting_id not in titles:
            meeting = await service.meetings.get_meeting(i.meeting_id)
            titles[i.meeting_id] = meeting.title if meeting else None
        items.append({"id": i.id, "text": _clip(i.text), "assignee": i.assignee, "stated_time": i.stated_time, "meeting_id": i.meeting_id, "meeting_title": titles[i.meeting_id],
                      "support": i.support.value, "pending_review": True, "ref": {"screen": "meetings", "id": i.meeting_id}})
    return {"status": "ok" if rows else "empty", "count": len(rows), "items": items}


async def _reviews(*, access, notepad_service, analysis_service, **_) -> dict:
    notes, actions = None, None
    failures = 0
    try:
        notes = await _note_proposals(access, notepad_service)
    except Exception as exc:  # noqa: BLE001 - one queue failing must not hide the other
        log.warning("home note proposals unavailable: %s", type(exc).__name__)
        failures += 1
        notes = {"status": "unavailable", "count": 0, "items": []}
    try:
        actions = await _meeting_actions(access, analysis_service)
    except Exception as exc:  # noqa: BLE001
        log.warning("home meeting actions unavailable: %s", type(exc).__name__)
        failures += 1
        actions = {"status": "unavailable", "count": 0, "items": []}
    states = {notes["status"], actions["status"]}
    status = "unavailable" if failures == 2 else "partial" if failures == 1 else "off" if states == {"off"} else "ok" if notes["count"] + actions["count"] else "empty"
    return {"status": status, "total": notes["count"] + actions["count"], "note_proposals": notes, "meeting_actions": actions}


# -- weather ------------------------------------------------------------------------------------------------------------------

async def _weather(*, weather, persona, **_) -> dict:
    if weather is None:
        return {"status": "off"}
    return await weather.section(persona.location, persona.timezone)


_BUILDERS: dict[str, Callable[..., Awaitable[dict]]] = {"schedule": _schedule, "tasks": _tasks, "reminders": _reminders, "reviews": _reviews, "weather": _weather}


# -- the snapshot -------------------------------------------------------------------------------------------------------------

def quick_actions(snapshot: dict) -> list[dict]:
    """Deterministic shortcuts derived from what the snapshot shows; each is a navigation reference, never an action taken."""
    out: list[dict] = []
    reviews, reminders, schedule = snapshot.get("reviews") or {}, snapshot.get("reminders") or {}, snapshot.get("schedule") or {}
    nxt = schedule.get("next_event")
    if nxt and nxt.get("classification") == EventClass.MEETING.value:
        out.append({"id": "record_meeting", "label": "Record a meeting", "ref": {"screen": "meetings"}})
    notes = (reviews.get("note_proposals") or {}).get("count") or 0
    acts = (reviews.get("meeting_actions") or {}).get("count") or 0
    if notes:
        out.append({"id": "review_notes", "label": f"Review {notes} note suggestion{'s' if notes != 1 else ''}", "ref": {"screen": "notes"}})
    if acts:
        out.append({"id": "review_actions", "label": f"Review {acts} meeting action{'s' if acts != 1 else ''}", "ref": {"screen": "meetings"}})
    if (reminders.get("counts") or {}).get("overdue"):
        out.append({"id": "overdue", "label": "Overdue reminders", "ref": {"screen": "reminders"}})
    out += [
        {"id": "add_task", "label": "Add a task", "ref": {"screen": "tasks"}},
        {"id": "new_note", "label": "New note", "ref": {"screen": "notes"}},
        {"id": "ask", "label": "Ask Reachy", "ref": {"screen": "talk"}},
    ]
    return out


async def build_home(
    *, access: AccessContext, now: datetime, persona, calendar_store, task_store, planner_store, notepad_service=None, analysis_service=None, weather=None,
    sections: tuple[str, ...] = SECTIONS,
) -> dict:
    zone = ZoneInfo(persona.timezone)
    wanted = tuple(s for s in SECTIONS if s in sections)
    snapshot: dict = {"generated_at": now.isoformat(), "timezone": str(zone.key), "date": now.astimezone(zone).date().isoformat()}
    restricted = access.sensitivity_ceiling is Privacy.PUBLIC  # a shared speaker or public channel: nothing is read, so nothing, not even a count, can leak
    for name in wanted:
        if restricted:
            snapshot[name] = {"status": "restricted"}
            continue
        try:
            snapshot[name] = await _BUILDERS[name](
                access=access, now=now, zone=zone, persona=persona, calendar_store=calendar_store, task_store=task_store, planner_store=planner_store,
                notepad_service=notepad_service, analysis_service=analysis_service, weather=weather,
            )
        except Exception as exc:  # noqa: BLE001 - a fixed code; the exception text may quote a record
            log.warning("home section %s unavailable: %s", name, type(exc).__name__)
            snapshot[name] = {"status": "unavailable", "error": "section_failed"}
    snapshot["sources"] = {name: snapshot[name]["status"] for name in wanted}
    snapshot["partial"] = any(s in {"unavailable", "partial"} for s in snapshot["sources"].values())
    snapshot["restricted"] = restricted
    snapshot["quick_actions"] = [] if restricted else quick_actions(snapshot)
    return snapshot
