"""Owned by companion-core (Phase 13). A DocumentChunk is what gets
embedded and retrieved; provenance (document title, optional section,
source) travels with every chunk so an answer can point back to where it
came from — the exit criterion ("Answers identify their supporting
document/section/page where available"). There's no `page` field: nothing
here ingests PDFs yet, so a page number would be fabricated; section comes
from markdown-style '#' headings when the source document has them, and is
None otherwise (same honesty-about-scope as the rest of this codebase's
placeholder-labelled pieces, except this one isn't a placeholder — it's a
real, if narrow, provenance model).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from shared.models.response import Privacy


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    document_title: str
    section: str | None = None
    content: str
    source: str
    chunk_index: int
    # Phase 44A: set once at ingest and shared by every chunk of a document. Unclassified means work-private; project_scope
    # None means unscoped (not public).
    sensitivity: Privacy = Privacy.WORK_PRIVATE
    project_scope: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RetrievedChunk(BaseModel):
    chunk: DocumentChunk
    score: float
