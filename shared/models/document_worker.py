"""Document worker request/response shapes (Phase 50A). Nothing here carries a filesystem path or a backend internal."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

DOCUMENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
DOCUMENT_ID_RE = re.compile(DOCUMENT_ID_PATTERN)
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class WorkerTier(StrEnum):
    FLASH = "flash"
    BASIC = "basic"
    STANDARD = "standard"


class WorkerState(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    PARTIAL = "partial"  # some pages are readable, others are still being parsed or beyond the page limit
    FAILED = "failed"


class DocumentStatus(BaseModel):
    document_id: str
    backend: str = "mineru"
    backend_ref: str  # opaque; shared by every Reachy document with the same bytes
    source_hash: str
    tier: WorkerTier
    state: WorkerState
    page_count: int | None = None
    page_limit_applied: bool = False  # the document has more pages than the worker parses
    error_code: str | None = None


class ParseRequest(BaseModel):
    tier: WorkerTier
    force: bool = False  # drop cached results for this document's bytes first (reprocess)


class ContentRange(BaseModel):
    start: str
    end: str


class ContentRead(BaseModel):
    document_id: str
    backend_ref: str
    tier: WorkerTier
    content: str
    ranges: list[ContentRange] = Field(default_factory=list)
    truncated: bool = False
    next_page_range: str | None = None
    next_after: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)


class SearchHit(BaseModel):
    snippet: str
    page: int | None = None  # None when the page could not be established; never inferred from position
    locator: str | None = None


class SearchResponse(BaseModel):
    document_id: str
    hits: list[SearchHit]
    complete: bool  # false when the scan limit was reached before the backend's results ran out


class DeleteResult(BaseModel):
    document_id: str
    deleted: bool
    verified: bool  # the document is no longer searchable or readable through the worker
    shared_hash_remaining: bool  # another Reachy document still uses the same bytes in the backend


class WorkerHealth(BaseModel):
    ok: bool
    engine_ready: bool
    telemetry_disabled: bool
    tiers: list[WorkerTier]
    detail: str | None = None
