"""Phase 49 (docs/phase-49.md): the data model for optional Notepad processing.

A JOB processes one immutable snapshot of a note (the text copied at enqueue, its content hash and the note's `updated_at` at that moment). A PROPOSAL is
extracted from that snapshot and does nothing until the owner accepts it: it lives in its own table and is not a task, a reminder or a memory. PROVENANCE links a
record created by an accepted proposal back to its note, snapshot hash and proposal."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from shared.models.response import Privacy

MAX_SNAPSHOT_CHARS = 20_000
MAX_PROPOSALS = 30
MAX_TEXT = 300
LEASE_SECONDS = 180
ACCEPTING_STALE_SECONDS = 120
PROMPT_VERSION = "notepad-extract-2"
MAX_TRANSCRIPT_CHARS = 60_000
MAX_LINKED_MEETINGS = 5
RECORD_NAMESPACE = uuid.UUID("49a0c0de-4949-4949-8949-49a0c0de4949")  # derives the id of the record a proposal creates, so a retry or crash can never create a second one


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_JOBS = (JobStatus.QUEUED, JobStatus.PROCESSING)


class Kind(StrEnum):
    TASK = "task"
    REMINDER = "reminder"
    EVENT = "event"
    REFERENCE = "reference"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    ACCEPTING = "accepting"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    NOTED = "noted"  # reference information: stays in the note, nothing to decide


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalise(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", text.casefold()).strip()


def fingerprint(evidence: str) -> str:
    """Identifies a source sentence across reprocessing, whatever the model calls it this time. Kind-agnostic: one sentence is one proposal for its note."""
    return hashlib.sha256(normalise(evidence).encode("utf-8")).hexdigest()


def transcript_source_key(meeting_id: str, segment: str | None, quote: str) -> str:
    return f"meeting:{meeting_id}:{segment or '-'}:{fingerprint(quote)}"


def record_id_for(proposal_id: str) -> str:
    return str(uuid.uuid5(RECORD_NAMESPACE, proposal_id))


class JobSource(BaseModel):
    """A linked meeting offered to one job. `text` is the transcript as it was at enqueue (an immutable snapshot, like the note); it is empty when the meeting was
    not included, and `reason` then says why (for example that its transcript is not ready yet)."""

    meeting_id: str
    title: str
    started_at: datetime | None = None
    included: bool = False
    reason: str | None = None
    text: str = ""
    hash: str | None = None
    sensitivity: Privacy = Privacy.WORK_PRIVATE

    def view(self) -> dict:
        return self.model_dump(mode="json", exclude={"text"})


class EvidenceRef(BaseModel):
    """Where one supporting quote really is. `speaker` is the label printed on the transcript line, copied as is: nothing here says who the speaker is."""

    kind: Literal["note", "meeting"]
    quote: str
    start: int
    end: int
    meeting_id: str | None = None
    title: str | None = None
    speaker: str | None = None
    segment: str | None = None  # the [m:ss] stamp of the transcript line: with the meeting id, the stable identity of the passage


def evidence_from(sources: list[EvidenceRef]) -> str:
    kinds = {s.kind for s in sources}
    return "both" if kinds == {"note", "meeting"} else "transcript" if kinds == {"meeting"} else "note"


class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    note_id: str
    note_title: str
    snapshot_text: str
    snapshot_hash: str
    note_updated_at: datetime
    timezone: str
    sensitivity: Privacy
    project_scope: str | None = None
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    error: str | None = None  # a fixed code, never provider output or note text
    model: str | None = None
    reprocess: bool = False
    proposal_count: int = 0
    inputs_hash: str = ""  # the note text and every included transcript; an identical request is answered by the job that already processed it
    sources: list[JobSource] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    lease_until: datetime | None = None

    def view(self) -> dict:
        data = self.model_dump(mode="json", exclude={"snapshot_text", "lease_until", "sources", "inputs_hash"})
        data["meetings"] = [s.view() for s in self.sources]
        return data


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    note_id: str
    snapshot_hash: str
    kind: Kind
    text: str
    evidence: str
    span_start: int
    span_end: int
    sources: list[EvidenceRef] = Field(default_factory=list)  # every supporting quote, each with its own origin; `evidence` is the first
    evidence_from: Literal["note", "transcript", "both"] = "note"
    # Stable identity of a transcript passage: the meeting id plus the normalised line text. One proposal exists per passage, whichever note's job found it; `associations`
    # (filled by the store on reads) maps every note that found it to the snapshot hash of that note's job. None for a proposal whose evidence is only in a note.
    source_key: str | None = None
    associations: dict[str, str] = Field(default_factory=dict)
    stated_time: str | None = None
    due_at: datetime | None = None
    ambiguity: list[str] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PENDING
    fingerprint: str
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    sensitivity: Privacy
    project_scope: str | None = None
    final_kind: Kind | None = None  # the values claimed at accept time; a crash retry reuses them
    final_text: str | None = None
    final_due_at: datetime | None = None
    edited: bool = False
    record_kind: str | None = None
    record_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    accepting_at: datetime | None = None
    decided_at: datetime | None = None

    def view(self, *, current_hash: str | None = None, viewed_note: str | None = None) -> dict:
        data = self.model_dump(mode="json", exclude={"fingerprint", "final_kind", "final_text", "final_due_at", "source_key", "associations"})
        found_with = self.associations.get(viewed_note, self.snapshot_hash) if viewed_note else self.snapshot_hash  # the hash of the viewing note's own job
        data["source_changed"] = current_hash is not None and current_hash != found_with
        data["note_ids"] = list(self.associations) or [self.note_id]
        return data


class Provenance(BaseModel):
    record_kind: str
    record_id: str
    note_id: str
    proposal_id: str
    snapshot_hash: str
    created_at: datetime = Field(default_factory=utcnow)


class MeetingLink(BaseModel):
    """Association of a note with a recorded meeting. It copies nothing and changes neither record: removing it (state rejected) deletes no note, no recording and no transcript."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    note_id: str
    meeting_id: str
    source: Literal["explicit", "temporal"]  # explicit: the owner linked it (also from inside a meeting); temporal: suggested from time overlap
    state: Literal["suggested", "confirmed", "rejected"]
    overlap_seconds: int | None = None
    title_match: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None
