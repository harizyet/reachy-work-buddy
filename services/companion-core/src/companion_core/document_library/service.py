"""The document library service (Phase 50B). It owns upload, the catalogue, metadata and deletion; ingestion into the backend and reading belong to 50C and later.

Rules that live here and nowhere else:
* a document's policy (sensitivity, project scope) is set by the owner's request and is never derived from, or lowered by, its content;
* the original is stored once by hash and re-verified before it is used; identical bytes uploaded twice are two documents with one blob;
* a document being deleted is unusable at once, and deletion is only complete when the backend confirms it holds nothing for that document;
* the blob is removed only when no Reachy document references its hash any more."""

from __future__ import annotations

import logging
import os
import zipfile
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path

from companion_core.document_library.models import (
    DEFAULT_SENSITIVITY,
    EXTENSION_ALIASES,
    FILE_TYPES,
    MAX_PROJECT,
    MAX_TITLE,
    MAX_UPLOAD_BYTES,
    Document,
    DocumentError,
    DocumentState,
    Priority,
    utcnow,
)
from companion_core.document_library.source_store import (
    SourceCorrupt,
    SourceRejected,
    SourceStore,
)
from companion_core.document_library.store import DocumentStore
from companion_core.document_library.worker_client import (
    DocumentWorkerClient,
    WorkerError,
)
from shared.models.response import Privacy

ENABLED_FLAG = "DOCUMENT_LIBRARY_ENABLED"
logger = logging.getLogger("companion_core.document_library")
UNSET = object()


def enabled() -> bool:
    return os.environ.get(ENABLED_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def max_upload_bytes() -> int:
    try:
        return max(1, int(os.environ.get("DOCUMENT_LIBRARY_MAX_UPLOAD_BYTES", MAX_UPLOAD_BYTES)))
    except ValueError:
        return MAX_UPLOAD_BYTES


def _extension(filename: str) -> str:
    ext = Path(filename.replace("\\", "/")).suffix.lower().lstrip(".")
    ext = EXTENSION_ALIASES.get(ext, ext)
    if ext not in FILE_TYPES:
        raise DocumentError(415, "That file type is not supported")
    return ext


def _check_docx(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as package:
            if "word/document.xml" not in package.namelist():
                raise SourceRejected(415, "That file type is not supported")
    except zipfile.BadZipFile:
        raise SourceRejected(415, "That file type is not supported") from None


def _clean_title(value: str | None, filename: str) -> str:
    title = " ".join((value or "").split()) or Path(filename.replace("\\", "/")).stem
    return title[:MAX_TITLE] or "Untitled"


def _clean_project(value: str | None) -> str | None:
    project = " ".join((value or "").split())
    if len(project) > MAX_PROJECT:
        raise DocumentError(422, "The project name is too long")
    return project or None


class DocumentService:
    def __init__(self, store: DocumentStore, sources: SourceStore, worker: DocumentWorkerClient | None, *, clock: Callable[[], datetime] = utcnow, max_bytes: int | None = None) -> None:
        self.store = store
        self.sources = sources
        self.worker = worker
        self.clock = clock
        self.max_bytes = max_bytes or max_upload_bytes()

    # --- upload and catalogue -------------------------------------------------------------------------------

    async def upload(
        self,
        filename: str,
        chunks: AsyncIterator[bytes],
        *,
        title: str | None = None,
        sensitivity: Privacy | None = None,
        project_scope: str | None = None,
        priority: Priority = Priority.BACKGROUND,
    ) -> Document:
        ext = _extension(filename)
        mime, magics = FILE_TYPES[ext]
        project = _clean_project(project_scope)
        try:
            source_hash, size, _new = await self.sources.put(
                chunks, max_bytes=self.max_bytes, head_ok=lambda head: any(head.startswith(m) for m in magics), validate=_check_docx if ext == "docx" else None
            )
        except SourceRejected as exc:
            raise DocumentError(exc.status, exc.detail) from None
        document = Document(
            title=_clean_title(title, filename), filename=Path(filename.replace("\\", "/")).name[:255] or f"document.{ext}", mime_type=mime, source_hash=source_hash, size_bytes=size,
            sensitivity=sensitivity or DEFAULT_SENSITIVITY, project_scope=project, processing_priority=priority, created_at=self.clock(), updated_at=self.clock(),
        )
        try:
            return await self.store.add(document)
        except Exception:
            if await self.store.count_by_hash(source_hash) == 0:
                await self.sources.delete(source_hash)  # the blob was ours alone; do not leave an orphan
            raise

    async def list_documents(self) -> list[Document]:
        return await self.store.list()

    async def get(self, document_id: str) -> Document:
        document = await self.store.get(document_id)
        if document is None:
            raise DocumentError(404, "No such document")
        return document

    async def require_usable(self, document_id: str) -> Document:
        """The check every read of a document's content starts from: it exists, is not being deleted and its original still matches its hash."""
        document = await self.get(document_id)
        if document.state is DocumentState.DELETING:
            raise DocumentError(404, "No such document")
        try:
            await self.sources.verify(document.source_hash)
        except SourceCorrupt:
            logger.error("a stored original no longer matches its hash (document %s)", document.id)
            raise DocumentError(409, "The stored original failed its integrity check") from None
        return document

    async def update_metadata(self, document_id: str, *, title=UNSET, project_scope=UNSET, sensitivity=UNSET, priority=UNSET) -> Document:
        fields: dict = {}
        if title is not UNSET:
            fields["title"] = _clean_title(title, (await self.get(document_id)).filename)
        if project_scope is not UNSET:
            fields["project_scope"] = _clean_project(project_scope)
        if sensitivity is not UNSET:
            if sensitivity is None:
                raise DocumentError(422, "Sensitivity cannot be cleared")
            fields["sensitivity"] = sensitivity
        if priority is not UNSET:
            if priority is None:
                raise DocumentError(422, "Priority cannot be cleared")
            fields["processing_priority"] = priority
        if not fields:
            return await self.get(document_id)
        updated = await self.store.update(document_id, self.clock(), **fields)
        if updated is None:
            raise DocumentError(404, "No such document")
        return updated

    # --- deletion -------------------------------------------------------------------------------------------

    async def delete(self, document_id: str) -> None:
        """Mark it deleting (unusable at once), have the backend forget it, then remove the record and, if no other document shares the bytes, the original.
        If the backend cannot confirm, the document stays in DELETING and finish_deletions() retries it; the caller is told to try again."""
        document = await self.store.begin_delete(document_id, self.clock())
        if document is None:
            raise DocumentError(404, "No such document")
        if not await self._finish(document):
            raise DocumentError(502, "The document is marked for deletion but the document worker could not confirm it yet; it will be retried")

    async def finish_deletions(self) -> int:
        """Retry every document stuck in DELETING (called at startup and when the worker returns). Returns how many were completed."""
        done = 0
        for document in await self.store.deleting():
            done += await self._finish(document)
        return done

    async def _finish(self, document: Document) -> bool:
        if document.backend_ref is not None:
            if self.worker is None:
                return False
            try:
                result = await self.worker.delete(document.id)
            except WorkerError as exc:
                logger.warning("backend deletion of a document not confirmed: %s", exc.code)
                return False
            if not result.verified:
                return False
        await self.store.remove(document.id)
        if await self.store.count_by_hash(document.source_hash) == 0:
            await self.sources.delete(document.source_hash)
        return True

