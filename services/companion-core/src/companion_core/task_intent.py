"""Placeholder intent detection for task capture/list/complete/search — same
honesty-about-scope as calendar_intent.py and privacy_classifier.py: prefix/
phrase matchers, not real NLU. Phase 11's exit criterion ("Agent can record
and later retrieve explicit follow-ups") needs the record/retrieve to be
genuinely backed by real storage, not that the language understanding be
sophisticated. Phase 10+/12+ reasoning replaces these matchers, not the
TaskStore they call.

Each `match_*` function returns the extracted argument (task text, or
search query) on a match, `None` otherwise — callers check in a fixed
precedence order (capture, complete, search, list) since capture phrases
are more specific and should win over an accidental substring collision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from companion_core.action_boundary import is_action_request
from companion_core.planner.models import Note, Reminder, ReminderStatus
from companion_core.tasks.models import Task

_CAPTURE_PREFIXES = (
    "remind me to ",
    "add a task to ",
    "add task ",
    "add task to ",
    "todo: ",
    "to-do: ",
    "note to self: ",
)

_COMPLETE_PREFIXES = ("complete task ", "mark done ", "mark task done ", "done with ", "finished ")

_SEARCH_PREFIXES = ("search tasks for ", "find task ", "search my tasks for ")

_LIST_PHRASES = (
    "my tasks",
    "list tasks",
    "list my tasks",
    "show my tasks",
    "what are my tasks",
    "my to-dos",
    "my todos",
)


def _match_prefix(text: str, prefixes: tuple[str, ...]) -> str | None:
    lowered = text.strip().lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text.strip()[len(prefix) :].strip()
    return None


def match_capture(text: str) -> str | None:
    return _match_prefix(text, _CAPTURE_PREFIXES) or None


def match_complete(text: str) -> str | None:
    return _match_prefix(text, _COMPLETE_PREFIXES) or None


def match_search(text: str) -> str | None:
    return _match_prefix(text, _SEARCH_PREFIXES) or None


_ASKING = (
    r"(?:do i have|have i got|what|which|show|list|tell me|check|any|are there|is there|got any)"
)
_TASK_QUERY = re.compile(rf"\b{_ASKING}\b.*\b(?:tasks?|to-?dos?)\b")
_REMINDER_QUERY = re.compile(rf"^(?!\s*(?:set|add|create|remind)\b).*\b{_ASKING}\b.*\breminders?\b")


_CONTRACTION = re.compile(r"\bwhat(?:'s|s)\b|\bwhat(?:'re|re)\b", re.IGNORECASE)


def normalise_question(text: str) -> str:
    """Curly apostrophes straightened and "what's"/"whats"/"what're" spelled out, so one pattern serves every common way of typing or dictating the question."""
    straight = text.replace("\u2019", "'").replace("\u2018", "'")
    return _CONTRACTION.sub(lambda m: "what is" if m.group(0).lower().endswith("s") else "what are", straight)


# A bare list request with no opener: "my tasks", "tasks for next week", "to-dos today".
BARE_TASK_LIST = re.compile(
    r"^(?:please\s+)?(?:my\s+)?(?:open\s+|pending\s+)?(?:tasks?|to-?dos?)"
    r"(?:\s+(?:for|due|on|in|this|next|today|tomorrow)\b[^:;]*)?\s*[?.!]*$"
)

Window = Literal["next_week", "this_week", "today", "tomorrow"]
_WINDOW = (
    ("next_week", re.compile(r"\bnext\s+week\b", re.IGNORECASE)),
    ("this_week", re.compile(r"\b(?:this\s+week|the\s+rest\s+of\s+(?:the|this)\s+week)\b", re.IGNORECASE)),
    ("tomorrow", re.compile(r"\btomorrow\b", re.IGNORECASE)),
    ("today", re.compile(r"\b(?:today|tonight)\b", re.IGNORECASE)),
)
# Time wording this module does not interpret. Seeing any of it means the request is NOT answered with a list for some other window.
_OTHER_TIME = re.compile(
    r"\b(?:yesterday|last\s+(?:night|week|month|year)|(?:this|next)\s+(?:month|year|weekend)|weekends?|overdue|"
    r"(?:after\s+next\s+week|week\s+after(?:\s+next)?)|(?:in\s+)?(?:\d+|two|three|four)\s+(?:days?|weeks?|months?)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thu(?:rs?)?|fri|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    r"\d{1,2}(?:st|nd|rd|th)|\d{1,2}[/-]\d{1,2})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TimeScope:
    window: Window | None
    problem: Literal["unsupported", "ambiguous"] | None = None


def time_scope(text: str) -> TimeScope:
    """The one supported window named in `text` (today, tomorrow, this week, next week), if any. A second window, or any other time wording, is a problem: the
    caller must say so rather than pick one."""
    found = [name for name, pattern in _WINDOW if pattern.search(text)]
    if _OTHER_TIME.search(text):
        return TimeScope(None, "unsupported")
    if len(found) > 1:
        return TimeScope(None, "ambiguous")
    return TimeScope(found[0] if found else None)


SCOPE_WORDS = {"next_week": "next week", "this_week": "this week", "today": "today", "tomorrow": "tomorrow"}
SCOPE_LIMITS = {
    "unsupported": "I can only filter by today, tomorrow, this week or next week, so I haven't listed anything for that. Ask for one of those, or for all your tasks.",
    "ambiguous": "That names more than one time range, so I haven't picked one. Ask about just one of today, tomorrow, this week or next week.",
}


# 44H's wish pattern also fires on "Do I have any tasks I need done?"; a question opener with a question mark is a read.
_QUESTION = re.compile(r"^\W*(?:do|does|did|have|has|is|are|what|which|how)\b[^.!;]*\?\s*$", re.IGNORECASE)


def _changes_something(text: str) -> bool:
    return is_action_request(text) and not _QUESTION.match(text.strip())


def is_list_query(text: str) -> bool:
    # A request that changes something ("delete my tasks") is never a list query, whatever words it shares with one (44H handles it).
    if _changes_something(text):
        return False
    lowered = normalise_question(text.strip()).lower()
    return any(phrase in lowered for phrase in _LIST_PHRASES) or bool(_TASK_QUERY.search(lowered)) or bool(BARE_TASK_LIST.match(lowered))


_NOTE_QUERY = re.compile(rf"^(?!\s*(?:take|make|write|add|create|save)\b).*\b{_ASKING}\b.*\bnotes\b")


def is_note_list_query(text: str) -> bool:
    if _changes_something(text):
        return False
    return bool(_NOTE_QUERY.search(text.strip().lower()))


def format_notes_reply(notes: list[Note]) -> str:
    if not notes:
        return "You have no notes."
    return "Your notes: " + "; ".join(n.title for n in notes) + "."


def is_reminder_list_query(text: str) -> bool:
    if _changes_something(text):
        return False
    return bool(_REMINDER_QUERY.search(text.strip().lower()))


def format_reminders_reply(reminders: list[Reminder], timezone: str) -> str:
    pending = [r for r in reminders if r.status == ReminderStatus.PENDING]
    if not pending:
        return "You have no upcoming reminders."
    zone = ZoneInfo(timezone)

    def when(due: datetime) -> str:
        return f"{due.astimezone(zone):%a %d %b at %I:%M %p}"

    return "Your reminders: " + "; ".join(f"{r.text} ({when(r.due_at)})" for r in pending) + "."


def format_capture_reply(task: Task) -> str:
    return f"Got it, I'll remember: '{task.text}'."


def format_list_reply(tasks: list[Task], scope: TimeScope | None = None) -> str:
    if scope is not None and scope.problem:
        return SCOPE_LIMITS[scope.problem]
    if not tasks:
        return "You have no open tasks."
    lines = "; ".join(t.text for t in tasks)
    if scope is not None and scope.window:
        # Tasks store no due date, so none can be placed in a window; nothing is inferred from the text or the creation time.
        return f"Tasks don't carry due dates, so none can be placed in {SCOPE_WORDS[scope.window]}. Your open tasks, all undated: {lines}."
    return f"Your open tasks: {lines}."


def format_complete_reply(task: Task | None, query: str) -> str:
    if task is None:
        return f"I couldn't find an open task matching '{query}'."
    return f"Marked '{task.text}' as done."


def format_search_reply(tasks: list[Task], query: str) -> str:
    if not tasks:
        return f"No tasks found matching '{query}'."
    lines = "; ".join(f"{t.text} ({t.status.value})" for t in tasks)
    return f"Tasks matching '{query}': {lines}."
