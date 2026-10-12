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
