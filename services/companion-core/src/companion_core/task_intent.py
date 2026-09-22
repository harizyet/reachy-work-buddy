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


def is_list_query(text: str) -> bool:
    lowered = text.strip().lower()
    return any(phrase in lowered for phrase in _LIST_PHRASES)


def format_capture_reply(task: Task) -> str:
    return f"Got it, I'll remember: '{task.text}'."


def format_list_reply(tasks: list[Task]) -> str:
    if not tasks:
        return "You have no open tasks."
    lines = "; ".join(t.text for t in tasks)
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
