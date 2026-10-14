"""The document library service (Phase 50B). It owns upload, the catalogue, metadata and deletion; ingestion into the backend and reading belong to 50C and later.

Rules that live here and nowhere else:
* a document's policy (sensitivity, project scope) is set by the owner's request and is never derived from, or lowered by, its content;
* the original is stored once by hash and re-verified before it is used; identical bytes uploaded twice are two documents with one blob;
* a document being deleted is unusable at once, and deletion is only complete when the backend confirms it holds nothing for that document;
* the blob is removed only when no Reachy document references its hash any more."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from pathlib import Path

from companion_core.document_library import summary
from companion_core.document_library.models import (
    DEFAULT_SENSITIVITY,
    EXTENSION_ALIASES,
    FILE_TYPES,
    MAX_PROJECT,
    MAX_TITLE,
    MAX_UPLOAD_BYTES,
    SYNCABLE,
    Document,
    DocumentError,
    DocumentOutput,
    DocumentState,
    OutputStatus,
    Priority,
    SummaryStyle,
    extension_of,
    next_tier,
    tier_for,
    utcnow,
)
from companion_core.document_library.qa import (
    MAX_PAGES,
    WHOLE_DOCUMENT_PAGES,
    Evidence,
    Passage,
    clean_page,
    keywords,
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
from companion_core.llm.client import ProviderUnavailable
from companion_core.semantic.access import scope_permits, within_ceiling
from companion_core.semantic.model import AccessContext
from shared.models.document_library import (
    DocumentContentOut,
    DocumentHitOut,
    DocumentSearchOut,
    InspectBlockOut,
    InspectPageOut,
)
from shared.models.document_worker import (
    DocumentStatus,
    ExportKind,
    WorkerState,
    WorkerTier,
)
from shared.models.response import Privacy

ENABLED_FLAG = "DOCUMENT_LIBRARY_ENABLED"
logger = logging.getLogger("companion_core.document_library")
UNSET = object()
def clean_page_text(content: str) -> str:
    return clean_page(content, summary.MAX_PAGE_CHARS)


EVIDENCE_TYPE = "derived_extraction"  # ADR 0034: parsed text is a machine's reading of the original, never the source itself
_STATE = {
    WorkerState.QUEUED: DocumentState.QUEUED,
    WorkerState.PROCESSING: DocumentState.PROCESSING,
    WorkerState.READY: DocumentState.READY,
    WorkerState.PARTIAL: DocumentState.PARTIAL,
    WorkerState.FAILED: DocumentState.FAILED,
}


def summary_max_pages() -> int:
    try:
        return max(1, int(os.environ.get("DOCUMENT_LIBRARY_SUMMARY_MAX_PAGES", "60")))
    except ValueError:
        return 60


def sync_seconds() -> float:
    try:
        return max(0.5, float(os.environ.get("DOCUMENT_LIBRARY_SYNC_SECONDS", "5")))
    except ValueError:
        return 5.0


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
    def __init__(self, store: DocumentStore, sources: SourceStore, worker: DocumentWorkerClient | None, *, clock: Callable[[], datetime] = utcnow, max_bytes: int | None = None, provider=None) -> None:
        self.store = store
        self.sources = sources
        self.worker = worker
        self.clock = clock
        self.max_bytes = max_bytes or max_upload_bytes()
        self._locks: dict[str, asyncio.Lock] = {}
        self.provider = provider  # async () -> (ask(messages, max_tokens) -> str, model name) | None: the LOCAL model only; summaries never leave this host
        self._tasks: dict[str, asyncio.Task] = {}
        self.summary_max_pages = summary_max_pages()
        self.deletion_listeners: list[Callable[[str], Awaitable[None]]] = []  # Phase 53: services holding derived data about a document are told, before the backend is asked, that it is going

    def _lock(self, document_id: str) -> asyncio.Lock:
        """One lock per document for submit, reprocess and delete, so a deletion can never finish before a submission it raced with (which would leave the worker holding a copy)."""
        return self._locks.setdefault(document_id, asyncio.Lock())

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
            await self.store.add(document)
        except Exception:
            if await self.store.count_by_hash(source_hash) == 0:
                await self.sources.delete(source_hash)  # the blob was ours alone; do not leave an orphan
            raise
        if self.worker is None:
            return document
        async with self._lock(document.id):
            return await self._try_submit(document)  # best effort: if the worker is down the document stays `uploaded` and the sync loop submits it later

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

    # --- extraction inspector (MinerU's page images, structured result and renderers, through the worker) ---------------

    @staticmethod
    def _safe_filename(stem: str, suffix: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "document"
        return f"{cleaned[:80]}{suffix}"

    async def inspect_page(self, document_id: str, access: AccessContext, page: int) -> InspectPageOut:
        document = await self._readable(document_id, access)  # exists, not deleting, original intact, class and project allowed, processed
        try:
            view = await self.worker.inspect_page(document.id, page)
        except WorkerError as exc:
            if exc.code == "page_not_found":
                raise DocumentError(404, "There is no such page") from None
            raise await self._worker_failed(document, exc) from None
        return InspectPageOut(
            document_id=document.id, title=document.title, source_hash=document.source_hash, state=document.state.value, tier=view.tier.value, next_tier=next_tier(view.tier.value),
            source_type=view.source_type, page=view.page, page_count=view.page_count, page_image=view.source_type in ("pdf", "png", "jpg"), width_pt=view.width_pt, height_pt=view.height_pt,
            blocks=[InspectBlockOut(block=b.block, type=b.type, bbox=b.bbox) for b in view.blocks], markdown=view.markdown, html=view.html,
        )

    async def inspect_image(self, document_id: str, access: AccessContext, page: int, block: int | None = None, *, image_format: str = "png") -> tuple[bytes, str]:
        document = await self._readable(document_id, access)
        try:
            return await self.worker.inspect_image(document.id, page, block, image_format=image_format)
        except WorkerError as exc:
            if exc.code in ("page_not_found", "asset_not_found", "no_page_image"):
                raise DocumentError(404, "There is no picture of that") from None
            raise await self._worker_failed(document, exc) from None

    async def export(self, document_id: str, access: AccessContext, kind: ExportKind) -> tuple[bytes, str, str]:
        """What MinerU extracted, as a download: (bytes, content type, file name). The file name is built from the title and the kind, never from a path."""
        document = await self._readable(document_id, access)
        try:
            data, mime, extension = await self.worker.export(document.id, kind)
        except WorkerError as exc:
            raise await self._worker_failed(document, exc) from None
        label = "" if kind is ExportKind.MARKDOWN or kind is ExportKind.HTML else f"-{kind.value.replace('_', '-')}"
        return data, mime, self._safe_filename(f"{document.title}-{document.tier}{label}", f".{re.sub(r'[^a-z0-9]', '', extension)[:8] or 'bin'}")

    async def original(self, document_id: str, access: AccessContext) -> tuple[bytes, str, str]:
        """The stored original, hash-verified, for download. Needs no worker: it works for an unprocessed or failed document too."""
        document = await self.require_usable(document_id)
        self.authorize(document, access)
        suffix = Path(document.filename).suffix.lower()
        try:
            data = await self.sources.read_verified(document.source_hash)
        except SourceCorrupt:
            raise DocumentError(409, "The stored original failed its integrity check") from None
        return data, document.mime_type, self._safe_filename(Path(document.filename).stem, suffix)

    # --- deletion -------------------------------------------------------------------------------------------

    async def delete(self, document_id: str) -> None:
        """Mark it deleting (unusable at once), have the backend forget it, then remove the record and, if no other document shares the bytes, the original.
        If the backend cannot confirm, the document stays in DELETING and finish_deletions() retries it; the caller is told to try again."""
        async with self._lock(document_id):
            document = await self.store.begin_delete(document_id, self.clock())
            if document is None:
                raise DocumentError(404, "No such document")
            finished = await self._finish(document)
        if not finished:
            raise DocumentError(502, "The document is marked for deletion but the document worker could not confirm it yet; it will be retried")

    async def finish_deletions(self) -> int:
        """Retry every document stuck in DELETING (called at startup and when the worker returns). Returns how many were completed."""
        done = 0
        for document in await self.store.deleting():
            async with self._lock(document.id):
                done += await self._finish(document)
        return done

    async def _cancel_tasks(self, document_id: str) -> None:
        for output_id, task in list(self._tasks.items()):
            output = await self.store.get_output(output_id)
            if output is not None and output.document_id == document_id and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _finish(self, document: Document) -> bool:
        for listener in self.deletion_listeners:
            with contextlib.suppress(Exception):
                await listener(document.id)  # idempotent: derived associations, estimates and findings are removed whether or not the backend confirms yet
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
        await self._cancel_tasks(document.id)
        await self.store.delete_outputs(document.id)  # derived outputs go with the document
        await self.store.remove(document.id)
        if await self.store.count_by_hash(document.source_hash) == 0:
            await self.sources.delete(document.source_hash)
        return True


    # --- processing: submit, sync, reprocess ------------------------------------------------------------------

    async def _apply(self, document_id: str, status: DocumentStatus) -> Document | None:
        return await self.store.update(
            document_id, self.clock(), state=_STATE[status.state], backend=status.backend, backend_ref=status.backend_ref, backend_revision=status.source_hash,
            tier=status.tier.value, page_count=status.page_count, error_code=status.error_code,
        )

    async def _fail(self, document_id: str, code: str) -> Document | None:
        return await self.store.update(document_id, self.clock(), state=DocumentState.FAILED, error_code=code)

    async def _submit(self, document: Document) -> Document | None:
        """Give the verified original to the worker and record its reference and state. Raises WorkerError; the caller decides whether that is transient. Call with the document's lock held."""
        current = await self.store.get(document.id)
        if current is None or current.state is DocumentState.DELETING:
            return current
        try:
            data = await self.sources.read_verified(current.source_hash)
        except SourceCorrupt:
            logger.error("a stored original no longer matches its hash (document %s); it is not sent to the worker", current.id)
            return await self._fail(current.id, "source_corrupt")
        tier = WorkerTier(current.tier or tier_for(current.mime_type, current.processing_priority))
        status = await self.worker.ingest(current.id, current.source_hash, tier, extension_of(current.mime_type), data)
        return await self._apply(current.id, status)

    @staticmethod
    def _transient(exc: WorkerError) -> bool:
        return exc.status == 0 or exc.status >= 500

    async def _try_submit(self, document: Document) -> Document:
        try:
            return await self._submit(document) or document
        except WorkerError as exc:
            if self._transient(exc):
                logger.info("the document worker is not available for a submission: %s", exc.code)
                return document
            return await self._fail(document.id, exc.code) or document

    async def sync_once(self, *, include_ready: bool = False) -> int:
        """One pass of the sync loop (`include_ready` also checks documents already READY against the worker, which is how a worker restored from nothing is noticed): submit documents the worker has not been given, and move the state of the others to what the worker reports. A worker that lost a document
        (for example rebuilt from nothing) is given it again from the authoritative original. Returns how many documents changed."""
        if self.worker is None:
            return 0
        changed = 0
        watched = (*SYNCABLE, DocumentState.READY) if include_ready else SYNCABLE
        candidates = await self.store.pending_sync()
        if include_ready:
            candidates += [d for d in await self.store.list() if d.state is DocumentState.READY]
        for listed in candidates:
            async with self._lock(listed.id):
                current = await self.store.get(listed.id)
                if current is None or current.state not in watched:
                    continue
                resubmitted = False
                try:
                    if current.state is DocumentState.UPLOADED:
                        new = await self._submit(current)
                    else:
                        try:
                            new = await self._apply(current.id, await self.worker.status(current.id))
                        except WorkerError as exc:
                            if exc.status != 404:
                                raise
                            await self.store.update(current.id, self.clock(), state=DocumentState.UPLOADED, backend_ref=None, backend_revision=None, page_count=None, error_code=None)
                            new = await self._submit(current)
                            resubmitted = True  # given to the worker again, whatever state it comes back in
                except WorkerError as exc:
                    if self._transient(exc):
                        continue
                    new = await self._fail(current.id, exc.code)
                if new is not None and (resubmitted or (new.state, new.page_count, new.error_code) != (current.state, current.page_count, current.error_code)):
                    changed += 1
        return changed

    async def reprocess(self, document_id: str, tier: WorkerTier | None = None) -> Document:
        """Parse the retained original again (never a patch of old results): the worker drops the cached parse for these bytes and starts over at `tier` (default: the tier policy)."""
        if self.worker is None:
            raise DocumentError(503, "The document worker is not configured")
        async with self._lock(document_id):
            document = await self.require_usable(document_id)
            chosen = tier or WorkerTier(tier_for(document.mime_type, document.processing_priority))
            await self.store.supersede_outputs(document_id, self.clock())  # what was derived from the old extraction is out of date from now on
            try:
                if document.backend_ref is None:
                    await self.store.update(document_id, self.clock(), tier=chosen.value, error_code=None)
                    updated = await self._submit(await self.get(document_id))
                else:
                    updated = await self._apply(document_id, await self.worker.parse(document_id, chosen, force=True))
            except WorkerError as exc:
                raise self._refusal(exc) from None
            if updated is None:
                raise DocumentError(404, "No such document")
            return updated

    @staticmethod
    def _refusal(exc: WorkerError) -> DocumentError:
        if exc.status == 0 or exc.status >= 500:
            return DocumentError(503, "The document worker is unavailable")
        if exc.code == "not_ready":
            return DocumentError(409, "The document is not processed yet")
        return DocumentError(502, "The document worker refused the request")

    async def _worker_failed(self, document: Document, exc: WorkerError) -> DocumentError:
        """A read the worker could not serve. If it says the parse is not there, our READY was stale (another document with the same bytes was reprocessed, or the worker lost its cache):
        take the worker's state now so the sync loop watches this document again, and tell the caller it is not ready."""
        if exc.code == "not_ready":
            try:
                await self._apply(document.id, await self.worker.status(document.id))
            except WorkerError:
                pass
        elif exc.status == 404:
            # The worker does not know this document at all (it was restored from nothing): give it back to the sync loop, which submits the authoritative original again.
            await self.store.update(document.id, self.clock(), state=DocumentState.UPLOADED, backend_ref=None, backend_revision=None, page_count=None, error_code=None)
            return DocumentError(409, "The document is not processed yet")
        return self._refusal(exc)

    # --- reading, always from the Reachy document id -------------------------------------------------------------

    @staticmethod
    def authorize(document: Document, access: AccessContext) -> None:
        """The check before any worker call that reads content: the channel's sensitivity ceiling and the project scope, from the Reachy record, never from the backend."""
        if not within_ceiling(document.sensitivity, access.sensitivity_ceiling) or not scope_permits(access, document.project_scope):
            raise DocumentError(403, "This document is not available here")

    async def _readable(self, document_id: str, access: AccessContext) -> Document:
        document = await self.require_usable(document_id)
        self.authorize(document, access)
        if self.worker is None:
            raise DocumentError(503, "The document worker is not configured")
        if document.state not in (DocumentState.READY, DocumentState.PARTIAL):
            raise DocumentError(409, "The document is not processed yet")
        return document

    def _content(self, document: Document, read) -> DocumentContentOut:
        return DocumentContentOut(
            document_id=document.id, title=document.title, source_hash=document.source_hash, evidence_type=EVIDENCE_TYPE, tier=read.tier.value, content=read.content,
            start=read.ranges[0].start if read.ranges else None, end=read.ranges[-1].end if read.ranges else None, truncated=read.truncated,
            next_page_range=read.next_page_range, next_after=read.next_after,
        )

    async def read(self, document_id: str, access: AccessContext, *, page_range: str | None = None, after: str | None = None, limit: int = 8000) -> DocumentContentOut:
        document = await self._readable(document_id, access)
        try:
            return self._content(document, await self.worker.read(document.id, page_range=page_range, after=after, limit=limit))
        except WorkerError as exc:
            raise await self._worker_failed(document, exc) from None

    async def read_locator(self, document_id: str, access: AccessContext, locator: str, *, context: int = 0, limit: int = 8000) -> DocumentContentOut:
        document = await self._readable(document_id, access)
        try:
            return self._content(document, await self.worker.read_locator(document.id, locator, context=context, limit=limit))
        except WorkerError as exc:
            if exc.status == 404:
                raise DocumentError(404, "No such location in the document") from None
            raise await self._worker_failed(document, exc) from None

    async def evidence_for_question(self, document_id: str, access: AccessContext, question: str) -> Evidence:
        """The excerpts of this one document that bear on a question: pages found by searching inside it (the whole text if it is only a few pages and nothing specific was found),
        each read from the worker. Raises DocumentError exactly as read/search do; an empty passage list means the document does not appear to cover the question."""
        document = await self._readable(document_id, access)
        pages: list[tuple[int, str | None]] = []
        try:
            result = await self.worker.search(document.id, " ".join(keywords(question)) or question, limit=MAX_PAGES)  # the worker ranks this document's own pages
            pages = [(h.page, h.locator) for h in result.hits if h.page is not None]
            if not pages and document.page_count and document.page_count <= WHOLE_DOCUMENT_PAGES:
                pages = [(n, None) for n in range(1, document.page_count + 1)]
            passages = []
            for page, locator in sorted(pages)[:MAX_PAGES]:
                text = clean_page((await self.worker.read(document.id, page_range=str(page), limit=8000)).content)
                if text:
                    passages.append(Passage(page=page, text=text, locator=locator))
        except WorkerError as exc:
            raise await self._worker_failed(document, exc) from None
        return Evidence(document=document, passages=passages)

    async def search(self, document_id: str, access: AccessContext, query: str, *, limit: int = 10) -> DocumentSearchOut:
        document = await self._readable(document_id, access)
        try:
            result = await self.worker.search(document.id, query, limit=limit)
        except WorkerError as exc:
            raise await self._worker_failed(document, exc) from None
        return DocumentSearchOut(
            document_id=document.id, title=document.title, source_hash=document.source_hash, evidence_type=EVIDENCE_TYPE, complete=result.complete,
            hits=[DocumentHitOut(snippet=h.snippet, page=h.page, locator=h.locator) for h in result.hits],
        )


    # --- summaries (50H) -----------------------------------------------------------------------------------------

    async def summaries(self, document_id: str, access: AccessContext) -> tuple[Document, list[DocumentOutput]]:
        document = await self.require_usable(document_id)
        self.authorize(document, access)
        return document, await self.store.list_outputs(document_id)

    async def summarize(self, document_id: str, access: AccessContext, style: SummaryStyle, *, force: bool = False) -> DocumentOutput:
        """Start (or return the current) summary of one style. The work runs in the background; poll `summaries`. A current ready summary is returned as it is unless `force`."""
        document = await self._readable(document_id, access)
        if self.provider is None:
            raise DocumentError(503, "No local model is configured for summaries")
        async with self._lock(document.id):
            if force:
                await self.store.supersede_outputs(document.id, self.clock(), kind="summary", style=style.value)
            output, created = await self.store.begin_output(
                DocumentOutput(document_id=document.id, kind="summary", style=style.value, source_hash=document.source_hash, tier=document.tier or "basic",
                               sensitivity=document.sensitivity, created_at=self.clock(), updated_at=self.clock())
            )
            if created:
                task = asyncio.create_task(self._run_summary(document, output.id, style))
                self._tasks[output.id] = task
                task.add_done_callback(lambda _t, key=output.id: self._tasks.pop(key, None))
        return output

    async def wait_for_summaries(self) -> None:
        """For tests and shutdown: wait until no summary is running."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    async def fail_interrupted_outputs(self) -> int:
        return await self.store.fail_running_outputs(self.clock())

    async def _fail_output(self, output_id: str, code: str, text: str = "") -> None:
        await self.store.finish_output(output_id, self.clock(), status=OutputStatus.FAILED, error_code=code, text=text)

    async def _run_summary(self, document: Document, output_id: str, style: SummaryStyle) -> None:
        try:
            provider = await self.provider()
            if provider is None:
                await self._fail_output(output_id, "no_local_model")
                return
            ask, model = provider
            count = document.page_count or 1
            last = min(count, self.summary_max_pages)
            pages: list[tuple[int, str]] = []
            for number in range(1, last + 1):
                text = clean_page_text(await self._page(document, number))
                if text:
                    pages.append((number, text))
            if sum(len(t) for _n, t in pages) < summary.SPARSE_CHARS_PER_PAGE * last:
                await self._fail_output(output_id, "sparse_text", summary.SPARSE_TEXT)
                return
            partial = f"pages 1-{last} of {count}" if count > last else None
            groups = summary.group_pages(pages)
            sections: list[dict] = []
            if len(groups) == 1:
                text = await ask(summary.single_messages(document.title, style, groups[0].text, partial=partial), summary.FINAL_TOKENS)
                sections.append(self._section(document, groups[0], text))
            else:
                notes = []
                for group in groups:
                    note = (await ask(summary.map_messages(document.title, group), summary.MAP_TOKENS)).strip()
                    notes.append((group, note))
                    sections.append(self._section(document, group, note))
                combined = [n for _g, n in notes]
                while sum(len(n) for n in combined) > summary.REDUCE_CHARS and len(combined) > 1:
                    batches, batch, size = [], [], 0
                    for note in combined:
                        if batch and size + len(note) > summary.REDUCE_CHARS:
                            batches.append(batch)
                            batch, size = [], 0
                        batch.append(note)
                        size += len(note)
                    batches.append(batch)
                    if len(batches) == len(combined):
                        break  # nothing can be merged within the budget; the final call receives clipped notes
                    combined = [(await ask(summary.combine_messages(document.title, "\n\n".join(b)), summary.MAP_TOKENS)).strip() for b in batches]
                text = await ask(summary.final_messages(document.title, style, "\n\n".join(combined)[: summary.REDUCE_CHARS * 2], partial=partial), summary.FINAL_TOKENS)
            current = await self.store.get(document.id)
            if current is None or current.state is DocumentState.DELETING:
                return  # the document went away while this ran; its outputs are removed with it
            await self.store.finish_output(
                output_id, self.clock(), status=OutputStatus.READY, text=text.strip(), sections=tuple(sections), pages_covered=f"1-{last}" if last > 1 else "1",
                page_count=count, truncated=count > last, model=model, error_code=None,
            )
            if current.tier != document.tier or current.backend_revision != document.backend_revision:
                await self.store.supersede_outputs(document.id, self.clock(), kind="summary", style=style.value)  # reprocessed while this ran: out of date on arrival
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self._fail_output(output_id, "cancelled")
            raise
        except WorkerError as exc:
            await self._fail_output(output_id, "worker_unavailable" if self._transient(exc) else "worker_refused")
        except ProviderUnavailable:
            await self._fail_output(output_id, "model_unavailable")
        except Exception:
            logger.exception("summary generation failed")
            await self._fail_output(output_id, "error")

    async def _page(self, document: Document, number: int) -> str:
        return (await self.worker.read(document.id, page_range=str(number), limit=30000)).content

    @staticmethod
    def _section(document: Document, group: summary.Group, text: str) -> dict:
        locator = f"doc:{document.backend_ref}/tier:{document.tier}/page:{group.start}" if document.backend_ref and document.tier else None
        return {"pages": group.pages, "start_page": group.start, "end_page": group.end, "summary": text.strip(), "locator": locator}


def reconcile_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get("DOCUMENT_LIBRARY_RECONCILE_SECONDS", "300")))
    except ValueError:
        return 300.0


async def run_sync_loop(service: DocumentService, interval: float, reconcile_every: float | None = None) -> None:
    """Keep document states current and submit what is waiting. Errors are logged, never fatal; the interval is DOCUMENT_LIBRARY_SYNC_SECONDS. Every `reconcile_every` seconds
    (DOCUMENT_LIBRARY_RECONCILE_SECONDS, default 300) READY documents are also checked against the worker."""
    reconcile_every = reconcile_seconds() if reconcile_every is None else reconcile_every
    elapsed = 0.0
    while True:
        try:
            await service.sync_once(include_ready=elapsed >= reconcile_every)
            elapsed = 0.0 if elapsed >= reconcile_every else elapsed
            await service.finish_deletions()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("document sync pass failed")
        elapsed += interval
        await asyncio.sleep(interval)
