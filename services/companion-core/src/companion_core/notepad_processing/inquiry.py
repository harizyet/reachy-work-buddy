"""Phase 49E: natural questions about what the owner has to do, answered from stored records only.

The reply separates three things and never merges them: CONFIRMED tasks and reminders (records the owner created or approved), PENDING proposals (source-backed items extracted from
a note and awaiting review), and UNPROCESSED notes (never classified, so they may hold commitments nobody has looked at). No model writes any of it: every sentence is built from
the stores, under the turn's access rules. An empty task list never claims there are no commitments, and asking about a proposal never accepts it.

A question that names a note ("what did I write in the note called X") is not an inquiry: record_reference.parse claims it first, so its title can never reach this handler."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from companion_core.action_boundary import is_action_request
from companion_core.notepad_processing.models import Kind, ProposalStatus
from companion_core.semantic import access as rules
from companion_core.semantic.model import AccessContext
from companion_core.task_intent import (
    BARE_TASK_LIST,
    SCOPE_LIMITS,
    SCOPE_WORDS,
    about_the_topic,
    normalise_question,
    time_scope,
)
from companion_core.tasks.models import TaskStatus
from shared.models.response import Privacy

Window = Literal["next_week", "this_week", "today", "tomorrow"] | None
MAX_LISTED = 8

_OPENER = re.compile(r"^(?:(?:please|kindly|ok(?:ay)?|hey|so|and|also)[\s,]+|reachy[\s,:]+)*(?:what|which|do|does|did|have|has|any|are|is|show|list|tell|give|check|anything)\b", re.IGNORECASE)
_NEED_TO_DO = re.compile(
    r"\bwhat\s+(?:do|should|must|am)\s+i\s+(?:need|have|got|want|ought|supposed)?\s*(?:to\s+)?do\b|"
    r"\bwhat\s+is\s+(?:on\s+)?my\s+(?:plate|agenda|to-?do\s+list)\b|"
    r"\bwhat\s+(?:tasks?|to-?dos?|action\s+items?|commitments?)\s+(?:do\s+i\s+have|are\s+(?:there|pending|open|outstanding)|have\s+i\s+got)\b|"
    r"\bwhat\s+(?:is\s+|are\s+)?(?:on\s+)?my\s+(?:open\s+|pending\s+)?(?:tasks?|to-?dos?|action\s+items?|commitments?)\b|"
    r"\b(?:show|list|tell|give)(?:\s+me)?\s+(?:all\s+)?(?:of\s+)?my\s+(?:open\s+|pending\s+)?(?:tasks?|to-?dos?|action\s+items?)\b|"
    r"\b(?:do\s+i\s+have|have\s+i\s+got|any|are\s+there)\b.{0,40}\b(?:pending|open|outstanding|unfinished)?\s*(?:action\s+items?|tasks?|to-?dos?|commitments?)\b|"
    r"\bwhat\s+did\s+i\s+(?:agree|commit|promise|volunteer)\b.{0,30}\bdo\b",
    re.IGNORECASE,
)
_FROM_MEETING = re.compile(r"\b(?:meeting|call|standup|stand-up|catch-?up)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Inquiry:
    window: Window
    about_meeting: bool
    problem: Literal["unsupported", "ambiguous"] | None = None  # time wording that cannot be answered as asked; the reply says so and lists nothing


def match(text: str) -> Inquiry | None:
    """The inquiry in `text`, or None. Fixed patterns; no model. Questions only: an imperative never starts with these words."""
    stripped = normalise_question(text.strip())
    if not stripped or stripped.startswith("/") or is_action_request(stripped) or about_the_topic(stripped):
        return None
    if not (_OPENER.match(stripped) and _NEED_TO_DO.search(stripped)) and not BARE_TASK_LIST.match(stripped.lower()):
        return None
    scope = time_scope(stripped)
    return Inquiry(scope.window, bool(_FROM_MEETING.search(stripped)), scope.problem)


def window_bounds(window: Window, now: datetime, timezone: str) -> tuple[datetime, datetime] | None:
    if window is None:
        return None
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    if window == "next_week":
        return monday + timedelta(days=7), monday + timedelta(days=14)
    if window == "this_week":
        return now.astimezone(zone), monday + timedelta(days=7)
    if window == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=2)
    return now.astimezone(zone), today + timedelta(days=1)


def _readable(access: AccessContext, sensitivity: Privacy, project_scope: str | None) -> bool:
    return rules.within_ceiling(sensitivity, access.sensitivity_ceiling) and rules.scope_permits(access, project_scope)


RESTRICTED = "I keep your tasks and notes for the app and Telegram, not for a shared speaker. Ask me there."


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _list(items: list[str]) -> str:
    shown = items[:MAX_LISTED]
    more = len(items) - len(shown)
    return "; ".join(shown) + (f"; and {more} more" if more > 0 else "")


async def answer(inquiry: Inquiry, *, tasks, planner, notepad, access: AccessContext, now: datetime, timezone: str) -> str:
    """The reply. Built only from the stores, filtered by `access`."""
    if access.sensitivity_ceiling is Privacy.PUBLIC:
        return RESTRICTED  # a shared speaker: no task, reminder, note or proposal is read out, and nothing is said about whether any exist
    if inquiry.problem:
        return SCOPE_LIMITS[inquiry.problem]  # a fixed limitation: no list for a window that was not understood
    zone = ZoneInfo(timezone)
    bounds = window_bounds(inquiry.window, now, timezone)
    label = SCOPE_WORDS.get(inquiry.window or "", "")

    open_tasks = [t for t in await tasks.list_tasks(TaskStatus.OPEN) if _readable(access, t.sensitivity, t.project_scope)]
    reminders = [r for r in await planner.list_reminders() if r.status.value == "pending" and _readable(access, r.sensitivity, None)
                 and (bounds is None or bounds[0] <= r.due_at < bounds[1])]
    notes = {n.id: n for n in await planner.list_notes() if _readable(access, n.sensitivity, n.project_scope)}
    proposals = [p for p in await notepad.list_proposals(statuses=(ProposalStatus.PENDING, ProposalStatus.ACCEPTING))
                 if p.kind is not Kind.REFERENCE and any(n in notes for n in (p.associations or {p.note_id: ''})) and _readable(access, p.sensitivity, p.project_scope)
                 and (bounds is None or p.due_at is None or bounds[0] <= p.due_at < bounds[1])]
    processed = await notepad.processed_note_ids()
    unprocessed = [n for n in notes.values() if n.id not in processed and n.body.strip()]

    parts: list[str] = []
    if open_tasks:
        parts.append(f"You have {_count(len(open_tasks), 'confirmed task', 'confirmed tasks')}" + (f" (tasks don't carry due dates, so none can be placed in {label}; these are all undated)" if label else "")
                     + ": " + _list([t.text for t in open_tasks]) + ".")
    else:
        parts.append("You have no confirmed tasks.")
    if reminders:
        when = lambda r: f"{r.due_at.astimezone(zone):%a %d %b at %I:%M %p}"
        parts.append(f"Confirmed reminders{' ' + label if label else ''}: " + _list([f"{r.text} ({when(r)})" for r in reminders]) + ".")
    elif label:
        parts.append(f"You have no confirmed reminders {label}.")
    if proposals:
        labels: list[str] = []
        for p in proposals:
            backing = [notes[n].title for n in (p.associations or {p.note_id: ""}) if n in notes]
            for label in [*(f"your note “{t}”" for t in backing), *(f"the transcript of the meeting “{r.title}”" for r in p.sources if r.kind == "meeting")]:
                if label not in labels:
                    labels.append(label)
        parts.append(f"{_count(len(proposals), 'more action item', 'more action items')} extracted from {_join(labels)} "
                     f"{'is' if len(proposals) == 1 else 'are'} awaiting your review and not yet confirmed: " + _list([p.text for p in proposals]) + ".")
    if unprocessed:
        parts.append(f"{_count(len(unprocessed), 'note', 'notes')} {'has' if len(unprocessed) == 1 else 'have'} not been processed, so I can't say whether "
                     f"{'it holds' if len(unprocessed) == 1 else 'they hold'} other commitments.")
    if inquiry.about_meeting:
        parts.append("I don't extract action items from meetings automatically; I can only report what is in your tasks and processed notes.")
    return " ".join(parts)
