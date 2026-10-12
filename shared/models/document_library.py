"""Document library response shapes (Phase 50B). A document is described by its policy and state, never by a path or a backend internal."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from shared.models.response import Privacy


class DocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    mime_type: str
    size_bytes: int
    source_hash: str
    sensitivity: Privacy
    project_scope: str | None
    state: str
    processing_priority: str
    tier: str | None
    page_count: int | None
    error_code: str | None
    next_tier: str | None = None  # the extraction level to ask for if this one is not good enough (Advanced is the last)
    created_at: datetime
    updated_at: datetime


class DocumentContentOut(BaseModel):
    """A bounded read of a document's parsed text. `evidence_type` says it is derived extraction (OCR/parse), not the source; `source_hash` ties it to the original."""

    document_id: str
    title: str
    source_hash: str
    evidence_type: str
    tier: str
    content: str
    start: str | None = None  # first and last locators covered, for citation and continuation
    end: str | None = None
    truncated: bool = False
    next_page_range: str | None = None
    next_after: str | None = None


class DocumentHitOut(BaseModel):
    snippet: str
    page: int | None = None  # only when the text was found on that page
    locator: str | None = None


class DocumentSearchOut(BaseModel):
    document_id: str
    title: str
    source_hash: str
    evidence_type: str
    hits: list[DocumentHitOut]
    complete: bool


class Citation(BaseModel):
    """Where an answer's excerpt came from: the document and the page whose text was supplied to the model. Never a page the model wrote."""

    document_id: str
    title: str
    page: int
    locator: str | None = None
    source_hash: str | None = None  # the original the page was read from
    tier: str | None = None  # the extraction level it was read at
    evidence_type: str = "derived_extraction"


class SummarySectionOut(BaseModel):
    pages: str  # "1-4": the page group this section was written from
    start_page: int
    end_page: int
    summary: str
    locator: str | None = None


class SummaryOut(BaseModel):
    """A summary of one document: Reachy's reading of a machine's reading of the original (`evidence_type: derived_interpretation`). It names the original's hash and the extraction tier,
    carries the document's class, and says whether it is current (the document has not been reprocessed since) or stale."""

    id: str
    document_id: str
    title: str
    kind: str
    style: str
    status: str
    text: str
    sections: list[SummarySectionOut]
    pages_covered: str | None
    page_count: int | None
    truncated: bool
    source_hash: str
    tier: str
    sensitivity: Privacy
    model: str | None
    prompt_version: str
    stale: bool
    current: bool
    error_code: str | None
    evidence_type: str = "derived_interpretation"
    created_at: datetime
    updated_at: datetime


class InspectBlockOut(BaseModel):
    block: int
    type: str
    bbox: tuple[float, float, float, float] | None = None  # fractions of the page: left, top, right, bottom


class InspectPageOut(BaseModel):
    """One page as MinerU extracted it, with what the inspector needs to put it beside the original. Derived extraction, never the source."""

    document_id: str
    title: str
    source_hash: str
    evidence_type: str = "derived_extraction"
    state: str
    tier: str
    next_tier: str | None = None
    source_type: str
    page: int
    page_count: int
    page_image: bool  # MinerU can render a picture of the original page (PDF and image files)
    width_pt: float | None = None
    height_pt: float | None = None
    blocks: list[InspectBlockOut]
    markdown: str
    html: str  # MinerU's HTML for the page; untrusted text: show it only inside a sandbox without scripts
