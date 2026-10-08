"""Source adapters (Phase 44B, docs/phase-44.md sections 4 and 6): how each authoritative store describes itself to the knowledge
layer. An adapter answers one question, "what does this source say right now?", and it answers from the store, never from the index.
The indexing worker uses it to decide what to index; retrieval-time revalidation uses it to decide what may be returned and to read
the text. Nothing here writes to a store.

Visibility is the store's own rule: a forgotten or expired memory, a cancelled or unfinished meeting, a deleted record are all
"not visible" and produce no items."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from companion_core.meetings.corrections import current_text
from companion_core.meetings.models import READY_FOR_OUTPUTS
from companion_core.meetings.outputs import display_name, speakers
from companion_core.meetings.store import MeetingStore
from companion_core.memory.store import MemoryStore
from companion_core.planner.store import PlannerStore
from companion_core.rag.store import DocumentStore
from companion_core.semantic.model import ItemKind, SourceRef, SourceType
from companion_core.tasks.store import TaskStore
from shared.models.response import Privacy

# Summaries and minutes are written by a model from the transcript, so they rank below what people actually said.
GENERATED_CONFIDENCE = 0.5

Status = Literal["visible", "missing", "forgotten", "expired", "hidden"]


@dataclass(frozen=True)
class Indexable:
    """One retrievable part of a source, exactly as the source describes it now."""

    ref: SourceRef
    kind: ItemKind
    text: str  # what a reader is given; always taken from the source
    match_text: str  # what is searched and embedded; may add context (a speaker's name)
    sensitivity: Privacy
    local_only: bool
    project_scope: str | None
    confidence: float = 1.0
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    title: str | None = None
    section: str | None = None
    speaker: str | None = None
    start_seconds: float | None = None
    authority: Literal["source", "model_generated"] = "source"

    def version(self) -> str:
        """A hash of everything an index entry or a retrieval depends on. Two identical states hash alike on every machine; any
        change to the text, the classification, the scope, the validity or the provenance changes it."""
        parts = [
            self.ref.key, self.kind, self.text, self.match_text, self.sensitivity.value, self.local_only, self.project_scope,
            round(self.confidence, 6), _iso(self.observed_at), _iso(self.valid_from), _iso(self.valid_until), self.title,
            self.section, self.speaker, self.start_seconds, self.authority,
        ]
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


@dataclass
class SourceState:
    status: Status
    items: list[Indexable] = field(default_factory=list)


class SourceAdapter(Protocol):
    source_type: SourceType

    async def state(self, source_id: str) -> SourceState: ...

    async def list_ids(self) -> list[str]:
        """Ids of the sources that may currently be visible; reconciliation compares the index against this."""
        ...


def _ref(source_type: SourceType, source_id: str, locator: str | None = None) -> SourceRef:
    return SourceRef(source_type=source_type, source_id=source_id, locator=locator)


class MemoryAdapter:
    source_type: SourceType = "memory"

    def __init__(self, store: MemoryStore, clock=lambda: datetime.now(UTC)) -> None:
        self._store, self._clock = store, clock

    async def state(self, source_id: str) -> SourceState:
        record = await self._store.get_any(source_id)
        if record is None:
            return SourceState("missing")
        if record.forgotten_at is not None:
            return SourceState("forgotten")
        if record.expires_at is not None and record.expires_at <= self._clock():
            return SourceState("expired")
        item = Indexable(
            ref=_ref("memory", record.id), kind="memory", text=record.content, match_text=record.content,
            sensitivity=record.sensitivity, local_only=False, project_scope=record.project_scope,
            confidence=record.confidence, observed_at=record.created_at, valid_until=record.expires_at,
        )
        return SourceState("visible", [item])

    async def list_ids(self) -> list[str]:
        return [r.id for r in await self._store.list_memories()]


class DocumentAdapter:
    source_type: SourceType = "document"

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def state(self, source_id: str) -> SourceState:
        chunks = await self._store.get_document(source_id)
        if not chunks:
            return SourceState("missing")
        items = [
            Indexable(
                ref=_ref("document", source_id, str(c.chunk_index)), kind="document_chunk", text=c.content,
                match_text=f"{c.document_title}. {c.section}. {c.content}" if c.section else f"{c.document_title}. {c.content}",
                sensitivity=c.sensitivity, local_only=False, project_scope=c.project_scope, observed_at=c.created_at,
                title=c.document_title, section=c.section,
            )
            for c in chunks
        ]
        return SourceState("visible", items)

    async def list_ids(self) -> list[str]:
        return await self._store.list_document_ids()


class MeetingAdapter:
    """Segments carry the owner's accepted corrections and speaker names; the raw transcript is evidence and is never read here.
    Meeting speech never leaves the local models (ADR 0032), hence local_only."""

    source_type: SourceType = "meeting"

    def __init__(self, store: MeetingStore) -> None:
        self._store = store

    async def state(self, source_id: str) -> SourceState:
        meeting = await self._store.get_meeting(source_id)
        if meeting is None:
            return SourceState("missing")
        if meeting.status not in READY_FOR_OUTPUTS or not meeting.transcript_segments:
            return SourceState("hidden")  # cancelled, failed or not yet transcribed
        observed = meeting.started_at or meeting.created_at
        who = speakers(meeting)
        items: list[Indexable] = []
        for index, segment in enumerate(meeting.transcript_segments):
            text = current_text(meeting, index)
            if not text:
                continue
            label = who[index]
            name = display_name(meeting, label) if label else None
            items.append(Indexable(
                ref=_ref("meeting", meeting.id, str(index)), kind="meeting_segment", text=text,
                match_text=f"{name}: {text}" if name else text, sensitivity=meeting.sensitivity, local_only=True,
                project_scope=meeting.project_scope, observed_at=observed, title=meeting.title, speaker=name,
                start_seconds=float(segment.get("start", 0)),
            ))
        for kind, locator, output in (("meeting_summary", "summary", meeting.summary), ("meeting_minutes", "minutes", meeting.minutes)):
            if output is not None and output.text.strip():
                items.append(Indexable(
                    ref=_ref("meeting", meeting.id, locator), kind=kind, text=output.text.strip(), match_text=output.text.strip(),
                    sensitivity=meeting.sensitivity, local_only=True, project_scope=meeting.project_scope,
                    confidence=GENERATED_CONFIDENCE, observed_at=output.generated_at, title=meeting.title,
                    authority="model_generated",
                ))
        return SourceState("visible", items)

    async def list_ids(self) -> list[str]:
        return [m.id for m in await self._store.list_meetings()]


class NoteAdapter:
    source_type: SourceType = "note"

    def __init__(self, store: PlannerStore) -> None:
        self._store = store

    async def state(self, source_id: str) -> SourceState:
        note = await self._store.get_note(source_id)
        if note is None:
            return SourceState("missing")
        text = f"{note.title}\n{note.body}".strip()
        item = Indexable(
            ref=_ref("note", note.id), kind="note", text=text, match_text=text, sensitivity=note.sensitivity, local_only=False,
            project_scope=note.project_scope, observed_at=note.updated_at, title=note.title,
        )
        return SourceState("visible", [item])

    async def list_ids(self) -> list[str]:
        return [n.id for n in await self._store.list_notes()]


class TaskAdapter:
    source_type: SourceType = "task"

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    async def state(self, source_id: str) -> SourceState:
        task = await self._store.get_task(source_id)
        if task is None:
            return SourceState("missing")
        done = f" (done {task.completed_at:%Y-%m-%d})" if task.completed_at else ""
        item = Indexable(
            ref=_ref("task", task.id), kind="task", text=task.text, match_text=f"{task.text}{done}", sensitivity=task.sensitivity,
            local_only=False, project_scope=task.project_scope, observed_at=task.created_at,
        )
        return SourceState("visible", [item])

    async def list_ids(self) -> list[str]:
        return [t.id for t in await self._store.list_tasks()]


class ReminderAdapter:
    source_type: SourceType = "reminder"

    def __init__(self, store: PlannerStore) -> None:
        self._store = store

    async def state(self, source_id: str) -> SourceState:
        reminder = await self._store.get_reminder(source_id)
        if reminder is None:
            return SourceState("missing")
        item = Indexable(
            ref=_ref("reminder", reminder.id), kind="reminder", text=reminder.text,
            match_text=f"{reminder.text} (due {reminder.due_at:%Y-%m-%d %H:%M})", sensitivity=reminder.sensitivity,
            local_only=False, project_scope=None, observed_at=reminder.created_at,
        )
        return SourceState("visible", [item])

    async def list_ids(self) -> list[str]:
        return [r.id for r in await self._store.list_reminders()]


def build_adapters(
    *, memory: MemoryStore, documents: DocumentStore, meetings: MeetingStore, planner: PlannerStore, tasks: TaskStore,
    clock=lambda: datetime.now(UTC),
) -> dict[str, SourceAdapter]:
    adapters: list[SourceAdapter] = [
        MemoryAdapter(memory, clock), DocumentAdapter(documents), MeetingAdapter(meetings), NoteAdapter(planner),
        TaskAdapter(tasks), ReminderAdapter(planner),
    ]
    return {a.source_type: a for a in adapters}
