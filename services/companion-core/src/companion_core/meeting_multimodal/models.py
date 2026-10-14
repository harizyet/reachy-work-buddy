"""Phase 53 (docs/phase-53.md, ADR 0037): the data model for multimodal meeting intelligence.

Nothing here copies a transcript or a document. A LINK joins an existing meeting to an existing document. An ALIGNMENT is a derived estimate of which page of a linked document a stretch
(a WINDOW) of the transcript was about; it names its segments and its page and carries the revisions of both sources it was derived from, so it can be checked against them at any time.
A REVIEW is the owner's own decision about a window and is stored apart from the estimates, so a rerun can never overwrite it. An ITEM is a combined finding (decision, disagreement, open
question, action candidate, discussion point) whose evidence is a verified transcript quote and/or a verified document quote. Only a CONFIRMED action becomes a task."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from companion_core.notepad_processing.models import fingerprint, normalise
from shared.models.response import Privacy

ANALYSIS_VERSION = "slide-alignment-1"  # the windowing, scoring and certainty rules (docs/phase-53.md section 4)
ANALYSIS_PROMPT_VERSION = "multimodal-analysis-1"
ASK_PROMPT_VERSION = "multimodal-ask-1"
LEASE_SECONDS = 900
ACCEPTING_STALE_SECONDS = 120
MAX_TEXT = 300
MAX_ITEMS = 60
MAX_LINKS = 8  # documents attached to one meeting
RECORD_NAMESPACE = uuid.UUID("53a0c0de-5353-4153-8153-53a0c0de5353")
RECEIPT_NAMESPACE = uuid.UUID("53a0c0de-5353-4153-8153-53a0c0de5354")
_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}


def utcnow() -> datetime:
    return datetime.now(UTC)


def stricter(*levels: Privacy) -> Privacy:
    """The most restrictive of several classifications: a derived output is never less sensitive than any source it used."""
    return max(levels, key=_RANK.__getitem__)


def digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def action_record_id(item_id: str) -> str:
    """The id of the task a confirmed action creates: derived from the item, so a retry, a double click or a crash can never create a second task."""
    return str(uuid.uuid5(RECORD_NAMESPACE, item_id))


def locator(document_id: str, page: int) -> str:
    """The stable name of one page of one Reachy document (not the backend's internal locator): `doc:<document id>/page:<n>`."""
    return f"doc:{document_id}/page:{page}"


class Certainty(StrEnum):
    """How well the evidence supports an association. Assigned by fixed rules from observable signals (alignment.certainty_for), never by the model and never a probability."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Method(StrEnum):
    EXPLICIT = "explicit_reference"  # the speakers named a page and the name resolves to one attached document
    SEMANTIC = "semantic"  # the wording of the discussion matches the page
    NONE = "none"


class Relation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"  # a verified spoken quote and a verified page quote disagree
    UNRESOLVED = "unresolved"  # a page was named but could not be tied to one document, or the evidence conflicts


class ReviewDecision(StrEnum):
    CONFIRMED = "confirmed"  # the owner agrees with the suggested page
    REPLACED = "replaced"  # the owner chose another page
    NO_SLIDE = "no_slide"  # this stretch is not about any page
    REMOVED = "removed"  # this suggestion was wrong; a different later suggestion may still be shown


class RunKind(StrEnum):
    ALIGNMENT = "alignment"
    ANALYSIS = "analysis"


class RunStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_RUNS = (RunStatus.QUEUED, RunStatus.PROCESSING)


class Link(BaseModel):
    meeting_id: str
    document_id: str
    link_status: str = "linked"
    linked_by: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Run(BaseModel):
    """One request. It stores hashes of what it will read, never the text: the runner reads the meeting and the documents again and refuses to continue if either changed."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meeting_id: str
    kind: RunKind
    status: RunStatus = RunStatus.QUEUED
    ceiling: Privacy = Privacy.WORK_PRIVATE  # the requesting channel's access ceiling: the runner reads documents with exactly this, never more
    transcript_hash: str
    doc_revisions: dict[str, str] = Field(default_factory=dict)
    inputs_hash: str  # transcript, document revisions and the rule/prompt version: an identical request is answered by the run that already did it
    attempts: int = 0
    error: str | None = None  # a fixed code, never provider output or source text
    model: str | None = None
    force: bool = False
    stats: dict[str, int | float] = Field(default_factory=dict)  # counts and milliseconds only
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    lease_until: datetime | None = None

    def view(self) -> dict:
        return self.model_dump(mode="json", exclude={"lease_until", "inputs_hash", "doc_revisions", "ceiling"})


class Alt(BaseModel):
    document_id: str
    page: int
    locator: str
    title: str | None = None


class Contradiction(BaseModel):
    """Both sides are quotes that were found, character for character, in the page and in the window. That they disagree is the model's reading and is shown as such."""

    document_id: str
    page: int
    slide_quote: str
    spoken_quote: str


class Alignment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    meeting_id: str
    window_key: str  # "<first>-<last>" segment index
    segment_ids: list[int]
    start: float
    end: float
    document_id: str | None = None
    page: int | None = None
    locator: str | None = None
    slide_title: str | None = None
    alternatives: list[Alt] = Field(default_factory=list)
    certainty: Certainty = Certainty.UNKNOWN
    method: Method = Method.NONE
    relation: Relation = Relation.SUPPORTS
    reason: str = ""  # built from the observable signals only (see alignment.explain)
    model_note: str | None = None  # the model's own short comment, kept apart and shown as model-written
    shared_terms: list[str] = Field(default_factory=list)
    explicit_refs: list[str] = Field(default_factory=list)  # what the speakers said ("slide 7") and how it resolved
    contradictions: list[Contradiction] = Field(default_factory=list)
    transcript_revision: str  # the current text of exactly these segments when the estimate was made
    document_revision: str = ""  # the chosen document's revision (its original, parser revision and extraction tier)
    analysis_version: str = ANALYSIS_VERSION
    model: str | None = None
    sensitivity: Privacy
    project_scope: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Review(BaseModel):
    """The owner's decision for one window. It records the revisions of the sources it was made against; if either changes it must be confirmed again before it counts."""

    meeting_id: str
    window_key: str
    decision: ReviewDecision
    document_id: str | None = None
    page: int | None = None
    rejected_document_id: str | None = None  # for REMOVED: the suggestion that was judged wrong, so only that one stays hidden after a rerun
    rejected_page: int | None = None
    transcript_revision: str
    document_revision: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ItemKind(StrEnum):
    DISCUSSION = "discussion"
    DECISION = "decision"
    DISAGREEMENT = "disagreement"  # what a page says versus what was said: needs a verified quote from each
    OPEN_QUESTION = "open_question"
    ACTION = "action"


class ItemStatus(StrEnum):
    PENDING = "pending"
    ACCEPTING = "accepting"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    NOTED = "noted"


class Support(StrEnum):
    STATED = "stated"
    UNCERTAIN = "uncertain"


class Cite(BaseModel):
    """One verified quote. `source` says where it came from, and the two kinds carry different authority: what a speaker said (transcript) and what a page says (document)."""

    source: str  # "transcript" | "document"
    quote: str
    # transcript
    segment: int | None = None
    segments: list[int] = Field(default_factory=list)
    start: float | None = None
    end: float | None = None
    speaker: str | None = None
    # document
    document_id: str | None = None
    page: int | None = None
    locator: str | None = None
    source_hash: str | None = None
    revision: str | None = None


class Item(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    meeting_id: str
    transcript_hash: str
    kind: ItemKind
    text: str
    evidence: list[Cite] = Field(min_length=1)
    assignee: str | None = None
    stated_time: str | None = None
    ambiguity: list[str] = Field(default_factory=list)
    support: Support = Support.UNCERTAIN
    status: ItemStatus
    fingerprint: str
    model: str | None = None
    prompt_version: str = ANALYSIS_PROMPT_VERSION
    sensitivity: Privacy
    project_scope: str | None = None
    final_text: str | None = None
    edited: bool = False
    record_kind: str | None = None
    record_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    accepting_at: datetime | None = None
    decided_at: datetime | None = None

    def segment_ids(self) -> set[int]:
        return {n for c in self.evidence if c.source == "transcript" for n in (c.segments or ([c.segment] if c.segment is not None else []))}

    def document_ids(self) -> set[str]:
        return {c.document_id for c in self.evidence if c.source == "document" and c.document_id}


def item_fingerprint(kind: ItemKind, cite: Cite) -> str:
    """Exact-duplicate guard (also a unique index): the kind and the normalised first quote, with its page for a document quote."""
    return fingerprint(f"{kind.value} {cite.document_id or ''} {cite.page or ''} {cite.quote}")


def _words(text: str) -> set[str]:
    return {w for w in normalise(text).split() if len(w) > 1}


def _pages(item: Item) -> set[tuple[str, int]]:
    return {(c.document_id, c.page) for c in item.evidence if c.source == "document" and c.document_id and c.page is not None}


def same_item(a: Item, b: Item) -> bool:
    """One finding found twice: the same kind over the same stretch (or page) with quotes that are the same words, or wording that is. A re-analysis never brings back a dismissed one."""
    if a.kind is not b.kind or not (a.segment_ids() & b.segment_ids() or _pages(a) & _pages(b)):
        return False
    qa, qb = _words(a.evidence[0].quote), _words(b.evidence[0].quote)
    if qa and qb and (qa <= qb or qb <= qa or len(qa & qb) / len(qa | qb) >= 0.5):
        return True
    ta, tb = _words(a.text), _words(b.text)
    return bool(ta and tb and len(ta & tb) / len(ta | tb) >= 0.6)
