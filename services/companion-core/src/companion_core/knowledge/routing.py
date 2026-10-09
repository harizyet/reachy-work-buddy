"""Deterministic, intent-aware routing for structured status questions (Phase 44E follow-up).

Questions such as "what tasks do I still have open?" or "which reminders do I have?" are not retrieval problems: the answer is the current
content of an authoritative store, and a lexical search over meeting transcripts answers them badly (the 44E first look returned filler
lines). This module classifies such a question with fixed patterns, reads the matching records straight from the stores, and returns them as
KnowledgeItems after the same access decision every other path uses (`semantic.access.decide`). It is exhaustive within a cap, so the
reply can say "that is the whole list".

No model takes part: not in the classification, the filter terms or the access decision. A model's words never widen access and never choose
a store. A question that matches no pattern is not routed (the caller falls back to retrieval); a question about an attached meeting is never
routed (the Phase 43 path is kept; `choose_path` makes that rule explicit and testable).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from companion_core.planner.models import ReminderStatus
from companion_core.planner.store import PlannerStore
from companion_core.semantic import access as rules
from companion_core.semantic.model import (
    AccessContext,
    KnowledgeItem,
    Provenance,
    SourceRef,
)
from companion_core.tasks.models import TaskStatus
from companion_core.tasks.store import TaskStore
from shared.models.response import Privacy

StatusIntent = Literal["open_tasks", "done_tasks", "reminders"]
Path = Literal["phase43", "status", "retrieval"]
MAX_ITEMS = 25  # a status list is exhaustive up to this many; beyond it the reply is told the list was cut

_TASK_WORD = r"(?:tasks?|to-?dos?|to do list|action items?|chores?)"
_OPEN_WORD = r"(?:open|outstanding|pending|remaining|unfinished|incomplete|left|still|active|due|owe|owed)"
_DONE_WORD = r"(?:done|completed?|finished|ticked off|closed)"
_PATTERNS: list[tuple[StatusIntent, re.Pattern[str]]] = [
    ("done_tasks", re.compile(rf"\b{_DONE_WORD}\b[^.?!]{{0,30}}\b{_TASK_WORD}\b|\b{_TASK_WORD}\b[^.?!]{{0,30}}\b(?:i|we)\b[^.?!]{{0,12}}\b{_DONE_WORD}\b|what (?:have|did) i (?:done|finished|completed)", re.IGNORECASE)),
    ("reminders", re.compile(r"\breminders?\b", re.IGNORECASE)),
    ("open_tasks", re.compile(
        rf"\b{_OPEN_WORD}\b[^.?!]{{0,40}}\b{_TASK_WORD}\b|\b{_TASK_WORD}\b[^.?!]{{0,40}}\b{_OPEN_WORD}\b|\bwhat (?:tasks?|to-?dos?)\b|"
        r"\b(?:anything|something|what(?:'s| is| do i have)?)\b[^.?!]{0,20}\boutstanding\b|\bwhat (?:do|should|must) i (?:still )?(?:have to|need to|got to) do\b|"
        rf"\bmy {_TASK_WORD}\b|\b(?:everything|anything|all|whatever)\b[^.?!]{{0,30}}\b(?:i|we)\b[^.?!]{{0,20}}\b(?:have|need|got|must|should) to (?:do|get done|finish|complete)\b|\bwhat(?:'s| is) (?:left|on my plate)\b|\boutstanding\b[^.?!]{{0,30}}\b(?:involv|for|with)", re.IGNORECASE)),
]
# Words after "involves/for/with/about" that name a subject worth filtering by; generic words are ignored.
_SUBJECT = re.compile(r"\b(?:involv\w*|for|with|about|assigned to|owned by|regarding|concerning)\s+(?:the\s+)?([A-Za-z][\w'-]{2,})", re.IGNORECASE)
_NOT_SUBJECT = {"me", "you", "my", "mine", "today", "tomorrow", "this", "that", "these", "those", "them", "now", "week", "month", "all", "anything", "everything",
                "something", "the", "and", "or", "any", "each", "every", "your", "our", "his", "her", "their", "its", "next", "last", "still", "yet"}
_MEETING_HINT = re.compile(r"\b(?:in|from|during|at) (?:this|the|that|today's) (?:meeting|call|review|sync)\b", re.IGNORECASE)


@dataclass(frozen=True)
class RoutedStatus:
    intent: StatusIntent
    subjects: tuple[str, ...]
    items: tuple[KnowledgeItem, ...]
    total: int  # records of that kind before the subject filter and the cap
    shown: int
    truncated: bool
    dropped: dict[str, int] = field(default_factory=dict)  # access decisions, by reason
    note: str = ""  # one line for the evidence frame: what was read and that the list is complete (or was cut)


def classify(query: str) -> tuple[StatusIntent, tuple[str, ...]] | None:
    """The status intent of a question and the subject words to filter by, or None. Fixed patterns; no model."""
    if _MEETING_HINT.search(query):
        return None  # about what was said in a meeting, not about the stores
    for intent, pattern in _PATTERNS:
        if pattern.search(query):
            subjects = tuple(dict.fromkeys(
                m.group(1) for m in _SUBJECT.finditer(query) if m.group(1).lower() not in _NOT_SUBJECT and not re.fullmatch(_TASK_WORD, m.group(1), re.IGNORECASE)
            ))
            return intent, subjects
    return None


def choose_path(query: str, *, attached_meeting: bool) -> Path:
    """Which evidence path a question takes. An attached meeting always keeps the Phase 43 whole-meeting path; a status question reads the
    stores; everything else is retrieval."""
    if attached_meeting:
        return "phase43"
    return "status" if classify(query) else "retrieval"


def _item(kind: str, source_type: str, source_id: str, text: str, sensitivity, scope, observed: datetime) -> KnowledgeItem:
    ref = SourceRef(source_type=source_type, source_id=source_id)  # type: ignore[arg-type]
    return KnowledgeItem(ref=ref, kind=kind, text=text, provenance=Provenance(ref=ref), sensitivity=sensitivity,  # type: ignore[arg-type]
                         local_only=False, project_scope=scope, observed_at=observed)


def sees_everything(access: AccessContext) -> bool:
    """True only when no access rule can have hidden a record from this caller (the top sensitivity tier and no project restriction)."""
    return access.sensitivity_ceiling == Privacy.SENSITIVE and access.project_scopes is None


RESTRICTED_REPLY = "I can't read out private records on a shared speaker. You can ask me this on your private channel."


def restricted_reply(access: AccessContext) -> str | None:
    """A fixed reply for a status question on a channel that may show nothing private (the public ceiling), or None. It is a constant: not built from the
    stores, the caller's records or a model, so it cannot reveal whether any restricted record exists, nor claim that none does. A model asked to word this
    from a neutral note still said "you have no tasks" in some runs (development record), which is why the safe wording is deterministic."""
    return RESTRICTED_REPLY if access.sensitivity_ceiling == Privacy.PUBLIC else None


def status_note(head: str, access: AccessContext, *, shown: int, truncated: bool) -> str:
    """The one line of the evidence frame for a status list. Wording rule: it must not reveal whether restricted records exist, so it is built from
    the caller's access and the count of what may be shown, never from what was withheld; two situations that differ only in hidden records give
    the same words. Completeness is claimed only for a caller who cannot have anything hidden."""
    if sees_everything(access):
        return f"{head}: " + (f"{shown} shown, the list was cut at {MAX_ITEMS}." if truncated else f"{shown} in all; the list is complete, so anything not listed does not exist.")
    tail = ("If nothing is shown, say that you cannot show any here and that the owner can ask on a private channel. "
            if access.sensitivity_ceiling == Privacy.PUBLIC else "")
    return (f"{head} that this channel may show: {shown}" + (f", cut at {MAX_ITEMS}" if truncated else "") + ". "
            "Do not say whether other records exist or do not exist, and do not say this is everything. " + tail).strip()


async def route_status(
    query: str, access: AccessContext, *, tasks: TaskStore, planner: PlannerStore, now: datetime
) -> RoutedStatus | None:
    """Read the authoritative stores for a status question. None when the question is not one. Every record passes `decide` for this caller
    before it is returned, and the counts reported are of what the caller may see."""
    found = classify(query)
    if found is None:
        return None
    intent, subjects = found
    candidates: list[KnowledgeItem] = []
    if intent in ("open_tasks", "done_tasks"):
        want = TaskStatus.OPEN if intent == "open_tasks" else TaskStatus.DONE
        for t in await tasks.list_tasks(want):
            label = "open" if t.status == TaskStatus.OPEN else f"done {t.completed_at:%Y-%m-%d}" if t.completed_at else "done"
            candidates.append(_item("task", "task", t.id, f"Task ({label}): {t.text}", t.sensitivity, t.project_scope, t.created_at))
        if intent == "open_tasks":  # notes that are action lists belong in a question about what is outstanding
            for n in await planner.list_notes():
                if re.search(r"action items?|to-?do|follow-?ups?", n.title, re.IGNORECASE):
                    candidates.append(_item("note", "note", n.id, f"{n.title}\n{n.body}".strip(), n.sensitivity, n.project_scope, n.updated_at))
    else:
        for r in await planner.list_reminders():
            if r.status != ReminderStatus.PENDING:
                continue
            candidates.append(_item("reminder", "reminder", r.id, f"Reminder (pending, due {r.due_at:%Y-%m-%d %H:%M}): {r.text}", r.sensitivity, None, r.created_at))
    total = len(candidates)
    dropped: dict[str, int] = {}
    allowed: list[KnowledgeItem] = []
    for item in candidates:
        reason = rules.decide(access, item)
        if reason is not None:
            dropped[reason] = dropped.get(reason, 0) + 1
        else:
            allowed.append(item)
    if subjects:
        lowered = [s.lower() for s in subjects]
        allowed = [i for i in allowed if any(s in i.text.lower() for s in lowered)]
    truncated = len(allowed) > MAX_ITEMS
    shown = allowed[:MAX_ITEMS]
    what = {"open_tasks": "open tasks (and action-item notes)", "done_tasks": "completed tasks", "reminders": "pending reminders"}[intent]
    scope = f" matching {', '.join(subjects)}" if subjects else ""
    head = f"These are the {what}{scope} read directly from the owner's stores at {now:%Y-%m-%d %H:%M} UTC"
    note = status_note(head, access, shown=len(shown), truncated=truncated)
    return RoutedStatus(intent, subjects, tuple(shown), total, len(shown), truncated, dropped, note)
