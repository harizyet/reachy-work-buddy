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
