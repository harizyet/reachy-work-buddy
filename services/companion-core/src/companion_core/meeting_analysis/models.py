"""Phase 31 (docs/phase-31.md): the data model for owner-requested meeting analysis.

A RUN analyses one immutable snapshot of a meeting's transcript (numbered segments as they read at enqueue, with a hash). An ITEM is a decision, an open question or an action
candidate extracted from that snapshot. Each item carries evidence: the segment index (the same index Phase 44 uses as the locator), the timestamps and speaker label copied from
the snapshot, and a quote verified to be inside that segment. Only a CONFIRMED action becomes a task; nothing here is a task, a memory or a note until the owner says so."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from companion_core.notepad_processing.models import (  # Phase 49's hashing and text normalisation, shared as is
    fingerprint,
    normalise,
)
from shared.models.response import Privacy

MAX_ITEMS = 60
MAX_TEXT = 300
MAX_CHUNKS = 12
CHUNK_CHARS = 6000  # leaves room for the instructions and the JSON answer in the 8k-token local window (ADR 0031)
LEASE_SECONDS = 900  # a long meeting is several sequential local-model calls
ACCEPTING_STALE_SECONDS = 120
PROMPT_VERSION = "meeting-analysis-1"
RECORD_NAMESPACE = uuid.UUID("31a0c0de-3131-4131-8131-31a0c0de3131")
RECEIPT_NAMESPACE = uuid.UUID("31a0c0de-3131-4131-8131-31a0c0de3132")


def utcnow() -> datetime:
    return datetime.now(UTC)


def action_record_id(item_id: str) -> str:
    """The id of the task an item creates: derived, so a retry, a double click or a crash can never create a second task."""
    return str(uuid.uuid5(RECORD_NAMESPACE, item_id))


class RunStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_RUNS = (RunStatus.QUEUED, RunStatus.PROCESSING)


class ItemKind(StrEnum):
    DECISION = "decision"
    OPEN_QUESTION = "open_question"
    ACTION = "action"


class ItemStatus(StrEnum):
    PENDING = "pending"  # an action candidate waiting for the owner
    ACCEPTING = "accepting"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    NOTED = "noted"  # a decision or open question: generated and shown with its evidence, nothing to decide


class Seg(BaseModel):
    """One transcript segment as it read when the run was enqueued. `index` is the position in the meeting's raw `transcript_segments`, which is never rewritten."""

    index: int
    start: float
    end: float
    speaker: str | None = None  # the label printed on the transcript line, copied as is: nothing here says who the speaker is
    text: str
    gap: bool = False  # the recording check flagged this stretch as exact silence: the words are probably not speech

    def stamp(self) -> str:
        return f"{int(self.start) // 60}:{int(self.start) % 60:02d}"


class Support(StrEnum):
    """How far the checks that CAN be made go. Neither value says the conclusion is true: the quote is always verified to be in the transcript, but whether it supports what the model concluded is for the owner."""

    STATED = "stated"  # the quote has wording consistent with the kind of finding and covers the item's own words
    UNCERTAIN = "uncertain"  # it does not: the item may be an idea, a topic, or the model's inference


class Evidence(BaseModel):
    """A quote and where it really is. STT segments are short fragments and a sentence often spans several, so the quote is located across consecutive segments: `segment` is
    the first one, `segments` all of them (every id verified against the snapshot), `start`/`end` run from the first segment's start to the last one's end, and `speaker` is the label
    printed on the first segment. `in_gap` means every segment lies in a stretch the recording check found silent."""

    segment: int
    segments: list[int] = Field(default_factory=list)
    start: float
    end: float
    speaker: str | None = None
    quote: str
    in_gap: bool = False


class Run(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meeting_id: str
    meeting_title: str
    transcript_hash: str
    segments: list[Seg]
    meeting_started_at: datetime | None = None
    timezone: str
    sensitivity: Privacy
    project_scope: str | None = None
    status: RunStatus = RunStatus.QUEUED
    attempts: int = 0
    error: str | None = None  # a fixed code, never provider output or transcript text
    model: str | None = None
    reprocess: bool = False
    item_count: int = 0
    rejected: dict[str, int] = Field(default_factory=dict)  # reasons and counts only
    inputs_hash: str = ""  # transcript hash and prompt version: an identical request is answered by the run that already processed it
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    lease_until: datetime | None = None

    def view(self) -> dict:
        return self.model_dump(mode="json", exclude={"segments", "lease_until", "inputs_hash"})


class Item(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    meeting_id: str
    transcript_hash: str
    kind: ItemKind
    text: str
    evidence: list[Evidence] = Field(min_length=1)
    assignee: str | None = None  # a name the quote itself contains, or the printed speaker label of a first-person commitment; never a guess
    stated_time: str | None = None
    due_at: datetime | None = None
    ambiguity: list[str] = Field(default_factory=list)
    support: Support = Support.UNCERTAIN
    status: ItemStatus
    fingerprint: str
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    sensitivity: Privacy
    project_scope: str | None = None
    final_text: str | None = None  # the values claimed at accept time; a crash retry reuses them
    edited: bool = False
    record_kind: str | None = None
    record_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    accepting_at: datetime | None = None
    decided_at: datetime | None = None

    def stamps(self) -> str:
        return ", ".join(f"[{int(e.start) // 60}:{int(e.start) % 60:02d}]" for e in self.evidence)


def item_fingerprint(kind: ItemKind, quote: str) -> str:
    """Exact-duplicate guard (also a unique index): the kind and the normalised quote. The meaning of "the same finding" across wordings is `same_finding`."""
    return fingerprint(f"{kind.value} {quote}")


def _tokens(text: str) -> set[str]:
    return {w for w in normalise(text).split() if len(w) > 1}


def _segments(item: Item) -> set[int]:
    return {n for e in item.evidence for n in (e.segments or [e.segment])}


def same_finding(a: Item, b: Item) -> bool:
    """One finding found twice: the same kind, overlapping transcript, and quotes that are the same words (one contained in the other, or mostly shared) or wording that is. Two different
    actions in one segment have different quotes and stay two items; a shorter or longer quote of one sentence, or new wording of it, is the same item."""
    if a.kind is not b.kind or not _segments(a) & _segments(b):
        return False
    qa, qb = _tokens(a.evidence[0].quote), _tokens(b.evidence[0].quote)
    if qa and qb and (qa <= qb or qb <= qa or len(qa & qb) / len(qa | qb) >= 0.5):
        return True
    ta, tb = _tokens(a.text), _tokens(b.text)
    return bool(ta and tb and len(ta & tb) / len(ta | tb) >= 0.6)
