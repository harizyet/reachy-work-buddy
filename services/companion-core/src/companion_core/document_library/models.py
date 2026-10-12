"""Phase 50B (docs/phase-50.md, ADR 0034): the Reachy document record.

Reachy owns the document's identity, its original (the content-addressed source store), its sensitivity, project scope and lifecycle state. The document backend (MinerU, behind the
document worker) owns parsing and holds only a derived copy, so `backend_ref` is an opaque pointer, never an identity: two Reachy documents with the same bytes share one
backend object and still have separate policy. Authorization always starts from `id`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from shared.models.response import Privacy

DEFAULT_SENSITIVITY = Privacy.WORK_PRIVATE  # the system-wide default for owner records; an upload that names no class gets this, and content never lowers it
MAX_TITLE = 200
MAX_PROJECT = 100
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # operational default, configurable (DOCUMENT_LIBRARY_MAX_UPLOAD_BYTES), not a product guarantee


def utcnow() -> datetime:
    return datetime.now(UTC)


class DocumentState(StrEnum):
    UPLOADED = "uploaded"  # the original is stored; the backend has not been given it
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    DELETING = "deleting"  # nothing may read it from here on; deletion is retried until the backend confirms


UPDATABLE_FIELDS = frozenset({"title", "project_scope", "sensitivity", "state", "backend", "backend_ref", "backend_revision", "tier", "processing_priority", "page_count", "error_code"})  # id, hash and the filename facts never change
SYNCABLE = (DocumentState.UPLOADED, DocumentState.QUEUED, DocumentState.PROCESSING, DocumentState.PARTIAL)  # states the sync loop still has work for


class Priority(StrEnum):
    BACKGROUND = "background"  # the default for a passive upload
    NORMAL = "normal"
    INTERACTIVE = "interactive"


# type by content: extension -> (mime type, first bytes). A docx is additionally checked to be an OOXML word package.
FILE_TYPES: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (b"PK\x03\x04",)),
}
EXTENSION_ALIASES = {"jpeg": "jpg"}
_EXTENSION_BY_MIME = {mime: ext for ext, (mime, _magic) in FILE_TYPES.items()}


def extension_of(mime_type: str) -> str:
    return _EXTENSION_BY_MIME[mime_type]


def tier_for(mime_type: str, priority: Priority) -> str:
    """The initial processing tier (50C; the full policy is 50D). Word documents carry native text, so Flash reads them fully; PDFs and images may be scans, so they get OCR (Basic) even in the
    background; an interactive request asks for the visual path (Standard)."""
    if priority is Priority.INTERACTIVE:
        return "standard"
    return "flash" if extension_of(mime_type) == "docx" else "basic"


@dataclass(frozen=True)
class Document:
    title: str
    filename: str
    mime_type: str
    source_hash: str
    size_bytes: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sensitivity: Privacy = DEFAULT_SENSITIVITY
    project_scope: str | None = None
    state: DocumentState = DocumentState.UPLOADED
    backend: str = "mineru"
    backend_ref: str | None = None
    backend_revision: str | None = None
    tier: str | None = None
    processing_priority: Priority = Priority.BACKGROUND
    page_count: int | None = None
    error_code: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


class DocumentError(Exception):
    """A refusal with a fixed message: never filenames, text or backend detail."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
