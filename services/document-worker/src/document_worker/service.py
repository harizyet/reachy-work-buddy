"""Document worker behaviour. Every rule from the 50A spike lives here, not in the route layer:

* policy and liveness belong to Reachy's document id; the backend object is shared by identical bytes;
* search is scoped to one document: its own parsed pages are ranked (ranking.py), so a hit's page is the page that was scored;
* nothing returned carries a filesystem path or a backend message;
* deletion forgets the working copy, cleans orphans, then verifies, and says whether identical bytes remain in use.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict
from collections.abc import Iterable

from document_worker import locators, ranking
from document_worker.config import Settings
from document_worker.engine import DocumentEngine, EngineError
from document_worker.store import EXTENSIONS, DocumentStore, Meta
from shared.models.document_types import PAGE_PICTURE_TYPES, file_ok, head_ok
from shared.models.document_worker import (
    SHA256_PATTERN,
    ContentRange,
    ContentRead,
    DeleteResult,
    DocumentStatus,
    ExportKind,
    LayoutBlockOut,
    PageInspection,
    SearchHit,
    SearchResponse,
    WorkerHealth,
    WorkerState,
    WorkerTier,
)

_PAGE_RANGE_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
_PAGE_MARKER_RE = re.compile(r"<!--\s*page \d+ of \d+\s*-->")
_BACKEND_LOCATOR = re.compile(r"doc:[0-9a-f]+/tier:[a-z]+/page:(\d+)(?:/block:(\d+))?")
_PAGE_IMAGE_TYPES = PAGE_PICTURE_TYPES  # MinerU renders page and block images from PDF and image sources only
_NOT_READY = {"tier_not_cached", "page_not_cached", "not_cached", "parse_not_required"}
_ALREADY_GONE = {"file_not_found", "doc_not_found"}
_PAGE_CACHE = 2000  # parsed pages kept in memory across all documents (a few MB)
logger = logging.getLogger(__name__)


class WorkerError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _engine_failure(exc: EngineError) -> WorkerError:
    logger.warning("engine error code=%s", exc.code)  # the code only: a backend message can carry a filesystem path
    if exc.code in _NOT_READY:
        return WorkerError(409, "not_ready")
    if exc.code in _ALREADY_GONE:
        return WorkerError(404, "not_found")
    return WorkerError(502, "engine_error")


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


class DocumentService:
    def __init__(self, engine: DocumentEngine, store: DocumentStore, settings: Settings) -> None:
        self.engine = engine
        self.store = store
        self.settings = settings
        self._pages: OrderedDict[tuple[str, str, int], str] = OrderedDict()

    # --- helpers -------------------------------------------------------------------------------------------------

    def _meta(self, document_id: str) -> Meta:
        try:
            meta = self.store.get(document_id)
        except ValueError:
            raise WorkerError(404, "not_found") from None
        if meta is None:
            raise WorkerError(404, "not_found")
        return meta

    def _tier(self, tier: WorkerTier) -> str:
        if tier not in self.settings.tiers:
            raise WorkerError(422, "tier_not_enabled")
        return tier.value

    def _page_range(self, extension: str) -> str | None:
        # The backend accepts a page range for PDFs only; other formats are parsed whole.
        return f"1-{self.settings.max_pages}" if extension == "pdf" else None

    def _forget_cache(self, backend_ref: str) -> None:
        for key in [k for k in self._pages if k[0] == backend_ref]:
            del self._pages[key]

    # --- lifecycle -----------------------------------------------------------------------------------------------

    def health(self) -> WorkerHealth:
        state = self.engine.health()
        ok = state.ready and state.telemetry_disabled
        return WorkerHealth(
            ok=ok,
            engine_ready=state.ready,
            telemetry_disabled=state.telemetry_disabled,
            tiers=list(self.settings.tiers),
            detail=None if ok else state.detail,
        )

    def ingest(self, document_id: str, source_hash: str, tier: WorkerTier, extension: str, chunks: Iterable[bytes]) -> DocumentStatus:
        if not re.match(SHA256_PATTERN, source_hash):
            raise WorkerError(422, "bad_hash")
        if extension not in EXTENSIONS:
            raise WorkerError(415, "unsupported_type")
        tier_name = self._tier(tier)
        existing = self._meta_or_none(document_id)
        if existing is not None:
            if existing.source_hash != source_hash:
                raise WorkerError(409, "document_id_in_use")
            return self.status(document_id)

        staging = self.store.staging_path(document_id)
        digest, size, head = hashlib.sha256(), 0, b""
        try:
            with staging.open("wb") as out:
                for chunk in chunks:
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise WorkerError(413, "too_large")
                    if len(head) < 8:
                        head = (head + chunk)[:8]
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != source_hash:
                raise WorkerError(400, "hash_mismatch")
            if not head_ok(extension, head) or not file_ok(extension, staging):  # the content must be what the type says, by its leading bytes and (packaged formats, text) as a whole
                raise WorkerError(415, "content_type_mismatch")
            path = self.store.source_path(document_id, extension)
            staging.replace(path)
            try:
                ticket = self.engine.ensure_parse(path, tier_name, self._page_range(extension), False)
            except EngineError as exc:
                raise _engine_failure(exc) from None
        except BaseException:
            self.store.remove(document_id)
            raise
        self.store.put(Meta(document_id, source_hash, extension, tier_name, ticket.backend_ref))
        return self.status(document_id)

    def _meta_or_none(self, document_id: str) -> Meta | None:
        try:
            return self._meta(document_id)
        except WorkerError:
            return None

    def status(self, document_id: str) -> DocumentStatus:
        meta = self._meta(document_id)
        try:
            summary = self.engine.parse_summary(meta.backend_ref, meta.tier)
            pages = self.engine.page_count(meta.backend_ref)
        except EngineError as exc:
            raise _engine_failure(exc) from None
        statuses = set(summary.statuses)
        done = "done" in statuses
        if not statuses:
            state = WorkerState.QUEUED
        elif statuses == {"done"}:
            state = WorkerState.READY
        elif "parsing" in statuses:
            state = WorkerState.PARTIAL if done else WorkerState.PROCESSING
        elif "pending" in statuses:
            state = WorkerState.PARTIAL if done else WorkerState.QUEUED
        elif "failed" in statuses:
            state = WorkerState.PARTIAL if done else WorkerState.FAILED
        else:
            state = WorkerState.QUEUED
        limited = pages is not None and pages > self.settings.max_pages
        if state is WorkerState.READY and limited:
            state = WorkerState.PARTIAL
        return DocumentStatus(
            document_id=document_id,
            backend_ref=meta.backend_ref,
            source_hash=meta.source_hash,
            tier=WorkerTier(meta.tier),
            state=state,
            page_count=pages,
            page_limit_applied=limited,
            error_code=summary.error_code,
        )

    def parse(self, document_id: str, tier: WorkerTier, force: bool) -> DocumentStatus:
        meta = self._meta(document_id)
        tier_name = self._tier(tier)
        path = self.store.source_path(document_id, meta.extension)
        try:
            if force:
                self.engine.invalidate(meta.backend_ref, tier_name)
                self._forget_cache(meta.backend_ref)
            self.engine.ensure_parse(path, tier_name, self._page_range(meta.extension), force)
        except EngineError as exc:
            raise _engine_failure(exc) from None
        meta.tier = tier_name
        self.store.put(meta)
        return self.status(document_id)

    # --- reading -------------------------------------------------------------------------------------------------

    def _checked(self, raw, meta: Meta, document_id: str) -> ContentRead:
        for start, end in raw.ranges:
            if not (locators.belongs_to(start, meta.backend_ref) and locators.belongs_to(end, meta.backend_ref)):
                raise WorkerError(502, "engine_error")  # a read must never return another document's evidence
        return ContentRead(
            document_id=document_id,
            backend_ref=meta.backend_ref,
            tier=WorkerTier(meta.tier),
            content=raw.content,
            ranges=[ContentRange(start=s, end=e) for s, e in raw.ranges],
            truncated=raw.truncated,
            next_page_range=raw.next_page_range,
            next_after=raw.next_after,
        )

    def read(self, document_id: str, page_range: str | None, after: str | None, limit: int) -> ContentRead:
        meta = self._meta(document_id)
        if page_range is not None and not _PAGE_RANGE_RE.match(page_range):
            raise WorkerError(422, "bad_page_range")
        if after is not None and not locators.belongs_to(after, meta.backend_ref):
            raise WorkerError(422, "bad_cursor")
        try:
            raw = self.engine.read(meta.backend_ref, meta.tier, page_range, after, limit)
        except EngineError as exc:
            raise _engine_failure(exc) from None
        return self._checked(raw, meta, document_id)

    def read_locator(self, document_id: str, locator: str, context: int, limit: int) -> ContentRead:
        meta = self._meta(document_id)
        if not locators.belongs_to(locator, meta.backend_ref):
            raise WorkerError(404, "not_found")
        try:
            raw = self.engine.read_locator(locator, context, limit)
        except EngineError as exc:
            raise _engine_failure(exc) from None
        return self._checked(raw, meta, document_id)

    def _page_text(self, meta: Meta, page: int) -> str:
        key = (meta.backend_ref, meta.tier, page)
        if key in self._pages:
            self._pages.move_to_end(key)
            return self._pages[key]
        raw = self.engine.read(meta.backend_ref, meta.tier, str(page), None, 30000)
        text = " ".join(_PAGE_MARKER_RE.sub("", raw.content).split())
        self._pages[key] = text
        while len(self._pages) > _PAGE_CACHE:
            self._pages.popitem(last=False)
        return text

    def search(self, document_id: str, query: str, limit: int) -> SearchResponse:
        """Rank THIS document's pages for the query (ranking.py). The backend's library-wide search is never used, so nothing of another document can appear, and the page of every hit is the page
        that was scored. `complete` is false when the document has more pages than the worker reads."""
        meta = self._meta(document_id)
        try:
            count = self.engine.page_count(meta.backend_ref) or 0
            last = min(count, self.settings.max_pages)
            pages = [(n, self._page_text(meta, n)) for n in range(1, last + 1)]
        except EngineError as exc:
            raise _engine_failure(exc) from None
        hits = [
            SearchHit(snippet=r.snippet, page=r.page, locator=locators.page_locator(meta.backend_ref, meta.tier, r.page))
            for r in ranking.rank([(n, t) for n, t in pages if t], query, limit)
        ]
        return SearchResponse(document_id=document_id, hits=hits, complete=count <= self.settings.max_pages)

    # --- extraction inspector (MinerU's own renderers and page images) --------------------------------------------------

    @staticmethod
    def _public_refs(text: str) -> str:
        """MinerU's markdown refers to figures by backend locator; the inspector refers to `#page-N-block-M` instead, so no backend identity or locator ever leaves the worker."""
        return _BACKEND_LOCATOR.sub(lambda m: f"#page-{m.group(1)}" + (f"-block-{m.group(2)}" if m.group(2) else ""), text)

    def _inspectable(self, document_id: str, page: int | None = None) -> tuple[Meta, int]:
        meta = self._meta(document_id)
        try:
            count = self.engine.page_count(meta.backend_ref) or 0
        except EngineError as exc:
            raise _engine_failure(exc) from None
        last = min(count, self.settings.max_pages)
        if page is not None and not 1 <= page <= last:
            raise WorkerError(404, "page_not_found")  # not "not_found": that code means the worker does not know the document at all, which callers treat as lost state
        return meta, count

    def inspect_page(self, document_id: str, page: int) -> PageInspection:
        meta, count = self._inspectable(document_id, page)
        try:
            raw = self.engine.read(meta.backend_ref, meta.tier, str(page), None, 30000)
            layout = self.engine.page_layout(meta.backend_ref, meta.tier, page)
            html = self.engine.page_html(meta.backend_ref, meta.tier, page)
        except EngineError as exc:
            raise _engine_failure(exc) from None
        return PageInspection(
            document_id=document_id, page=page, page_count=count, tier=WorkerTier(meta.tier), source_type=meta.extension, width_pt=layout.width_pt, height_pt=layout.height_pt,
            blocks=[LayoutBlockOut(block=b.block, type=b.type, bbox=b.bbox) for b in layout.blocks], markdown=self._public_refs(raw.content), html=html,
        )

    def inspect_image(self, document_id: str, page: int, block: int | None, image_format: str) -> tuple[bytes, str]:
        meta, _count = self._inspectable(document_id, page)
        if meta.extension not in _PAGE_IMAGE_TYPES:
            raise WorkerError(415, "no_page_image")
        try:
            image = self.engine.image(meta.backend_ref, meta.tier, page, block, image_format)
        except EngineError as exc:
            if exc.code in {"block_not_found", "asset_not_available", "bbox_not_available", "format_not_supported"}:
                raise WorkerError(404, "asset_not_found") from None
            raise _engine_failure(exc) from None
        return image.data, image.mime

    def export(self, document_id: str, kind: ExportKind) -> tuple[bytes, str, str]:
        """A download of what MinerU extracted: (bytes, content type, file extension)."""
        meta, count = self._inspectable(document_id)
        last = min(count, self.settings.max_pages)
        try:
            if kind is ExportKind.MARKDOWN:
                parts = [self._public_refs(self.engine.read(meta.backend_ref, meta.tier, str(n), None, 30000).content) for n in range(1, last + 1)]
                return "\n\n".join(parts).encode(), "text/markdown; charset=utf-8", "md"
            payload = self.engine.structured_export(meta.backend_ref, meta.tier, kind.value, last)
        except EngineError as exc:
            raise _engine_failure(exc) from None
        if kind is ExportKind.HTML:
            return payload, "text/html; charset=utf-8", "html"
        return payload, "application/json", "json"

    # --- deletion ------------------------------------------------------------------------------------------------

    def delete(self, document_id: str) -> DeleteResult:
        meta = self._meta_or_none(document_id)
        if meta is None:
            return DeleteResult(document_id=document_id, deleted=True, verified=True, shared_hash_remaining=False)
        path = self.store.source_path(document_id, meta.extension)
        try:
            self.engine.forget(path)
        except EngineError as exc:
            if exc.code not in _ALREADY_GONE:
                raise _engine_failure(exc) from None
        self.store.remove(document_id)
        self._forget_cache(meta.backend_ref)
        shared = self.store.paths_for_hash(meta.source_hash) > 0
        try:
            self.engine.cleanup_orphans()
            backend_clear = shared or not self.engine.has_active_files(meta.backend_ref)
        except EngineError as exc:
            raise _engine_failure(exc) from None
        return DeleteResult(
            document_id=document_id,
            deleted=True,
            verified=backend_clear and not path.exists() and self.store.get(document_id) is None,
            shared_hash_remaining=shared,
        )
