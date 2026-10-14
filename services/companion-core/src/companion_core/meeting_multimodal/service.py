"""Phase 53: attach documents to meetings, estimate which page was discussed, answer questions across both sources and analyse them together. docs/phase-53.md, ADR 0037.

Deterministic code around narrow local-model calls (choose a page, list findings, phrase an answer); the model never writes, authorizes or sets a certainty. Rules that live here:

* every operation starts from the caller's access context (the hub's trusted ceiling): the meeting AND each document are checked, and a source the caller cannot read is indistinguishable from
  one that does not exist (one 404, no counts, no titles). Attaching grants nothing: reading a document through a meeting needs the same access as reading it directly;
* a derived output is never less sensitive than any source it used, and the sensitivity is recomputed from the sources as they are now;
* nothing derived is trusted past its sources: estimates and findings carry the revisions of the transcript and the document they were made from and are compared to the current ones on every read;
* the owner's decisions are separate rows; a rerun never overwrites them;
* a finding becomes a task only through `accept` (derived task id, the existing receipt), never by itself."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import psycopg

from companion_core.document_library.access import access_from_ceiling
from companion_core.document_library.models import (
    Document,
    DocumentError,
    DocumentState,
)
from companion_core.document_library.service import DocumentService
from companion_core.meeting_analysis.service import snapshot, transcript_hash
from companion_core.meeting_multimodal import alignment as align_mod
from companion_core.meeting_multimodal import analysis as analysis_mod
from companion_core.meeting_multimodal import ask as ask_mod
from companion_core.meeting_multimodal.alignment import Deck, make_page, windows
from companion_core.meeting_multimodal.models import (
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_VERSION,
    ASK_PROMPT_VERSION,
    MAX_LINKS,
    MAX_TEXT,
    RECEIPT_NAMESPACE,
    Alignment,
    Certainty,
    Item,
    ItemKind,
    ItemStatus,
    Link,
    Review,
    ReviewDecision,
    Run,
    RunKind,
    RunStatus,
    action_record_id,
    digest,
    locator,
    stricter,
    utcnow,
)
from companion_core.meeting_multimodal.store import OPEN_ITEMS, MultimodalStore
from companion_core.meetings.models import READY_FOR_OUTPUTS, Meeting
from companion_core.notepad_processing.extraction import ExtractionFailed, locate
from companion_core.privacy_classifier import classify_privacy
from companion_core.semantic.access import scope_permits, within_ceiling
from companion_core.semantic.model import AccessContext
from shared.models.receipt import ActionReceipt
from shared.models.response import Privacy

log = logging.getLogger("companion_core.meeting_multimodal")

ENABLED_FLAG = "MEETING_MULTIMODAL_ENABLED"
RUN_TIMEOUT_SECONDS = 1800.0
MAX_DECK_PAGES = 150
PAGE_READ_LIMIT = 30000
_MARKER = re.compile(r"<!--\s*page \d+ of \d+\s*-->")
_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}
NO_SUCH_MEETING = "No such meeting"
NO_SUCH_DOCUMENT = "No such document"

Provider = Callable[[], Awaitable[tuple[align_mod.Ask, str] | None]]


def enabled() -> bool:
    return os.environ.get(ENABLED_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


class MultimodalError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def revision_of(document: Document) -> str:
    """What a derived page estimate depends on: the original (its hash), the parser's revision and extraction tier, and the page count. A reprocess that changes any of them changes this."""
    return digest(document.source_hash, document.backend_revision, document.tier, document.page_count, document.backend_ref)[:24]


def ready(document: Document) -> bool:
    return document.state in (DocumentState.READY, DocumentState.PARTIAL) and bool(document.page_count)


@dataclass
class Readable:
    link: Link
    document: Document


def counts_as_discussed(shown: dict | None, stale: bool) -> bool:
    """Whether a page shown for a window may be used beyond the transcript card itself (as context for an analysis, as a link in an answer, as 'this page was discussed'): the owner's valid decision, or an
    estimate of High or Medium certainty that is current. A Low estimate is shown dimly for the owner to look at and is otherwise not relied on."""
    if shown is None or stale or shown["authority"] == "owner_stale":
        return False
    return shown["authority"] == "owner" or shown["certainty"] in (Certainty.HIGH.value, Certainty.MEDIUM.value)


def state_of(run: Run | None) -> str:
    return "not_run" if run is None else run.status.value


class MeetingMultimodalService:
    def __init__(self, store: MultimodalStore, meetings, documents: DocumentService, tasks, planner, *, provider: Provider | None = None, clock: Callable[[], datetime] = utcnow) -> None:
        self.store = store
        self.meetings = meetings
        self.documents = documents
        self.tasks = tasks
        self.planner = planner
        self.provider = provider
        self.clock = clock
        self.counters: dict[str, int] = {}
        self.wake = asyncio.Event()

    def _count(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    # -- sources and access ------------------------------------------------------------------------------------------------

    async def _meeting(self, meeting_id: str, access: AccessContext) -> Meeting:
        meeting = await self.meetings.get_meeting(meeting_id)
        if meeting is None or not within_ceiling(meeting.sensitivity, access.sensitivity_ceiling) or not scope_permits(access, meeting.project_scope):
            raise MultimodalError(404, NO_SUCH_MEETING)  # one answer for "missing" and "not yours to see"
        return meeting

    @staticmethod
    def _ready_transcript(meeting: Meeting) -> None:
        if meeting.status not in READY_FOR_OUTPUTS or not meeting.transcript_segments:
            raise MultimodalError(409, "The transcript is not ready yet")

    async def _document(self, document_id: str, access: AccessContext) -> Document:
        try:
            document = await self.documents.require_usable(document_id)
            self.documents.authorize(document, access)
        except DocumentError as exc:
            if exc.status == 409:
                raise MultimodalError(409, exc.detail) from None
            raise MultimodalError(404, NO_SUCH_DOCUMENT) from None
        return document

    async def _readable(self, meeting_id: str, access: AccessContext) -> list[Readable]:
        """The attached documents this caller may use right now. A document that is gone, being deleted, unreadable here, or whose project no longer fits is simply absent."""
        out: list[Readable] = []
        for link in await self.store.list_links(meeting_id):
            try:
                out.append(Readable(link, await self._document(link.document_id, access)))
            except MultimodalError:
                continue
        return out

    @staticmethod
    def _may_see(sensitivity: Privacy, project_scope: str | None, access: AccessContext) -> bool:
        return within_ceiling(sensitivity, access.sensitivity_ceiling) and scope_permits(access, project_scope)

    @staticmethod
    def _visible(run: Run | None, access: AccessContext) -> Run | None:
        """A run made with a higher ceiling than this caller's read documents this caller may not see: its state and counts are not shown."""
        return run if run is not None and _RANK[run.ceiling] <= _RANK[access.sensitivity_ceiling] else None

    @staticmethod
    def _same_project(meeting: Meeting, document: Document) -> bool:
        return meeting.project_scope is None or document.project_scope is None or meeting.project_scope == document.project_scope

    def _effective_sensitivity(self, meeting: Meeting, docs: list[Document]) -> Privacy:
        return stricter(meeting.sensitivity, *(d.sensitivity for d in docs))

    async def load_deck(self, document: Document, access: AccessContext) -> Deck:
        """Read every page of a processed document through the existing library service (the same access check and worker as the inspector), never from the worker directly."""
        count = document.page_count or 0
        if count > MAX_DECK_PAGES:
            raise MultimodalError(422, "A linked document has too many pages to align")
        pages = []
        for number in range(1, count + 1):
            try:
                content = (await self.documents.read(document.id, access, page_range=str(number), limit=PAGE_READ_LIMIT)).content
            except DocumentError as exc:
                raise MultimodalError(404 if exc.status in (403, 404) else 409, NO_SUCH_DOCUMENT if exc.status in (403, 404) else exc.detail) from None
            pages.append(make_page(number, _MARKER.sub("", content).strip()))
        return Deck(document_id=document.id, title=document.title, revision=revision_of(document), pages=tuple(pages), source_hash=document.source_hash,
                    sensitivity=document.sensitivity, project_scope=document.project_scope)

    # -- attach and detach -------------------------------------------------------------------------------------------------

    async def link(self, meeting_id: str, document_id: str, access: AccessContext, *, linked_by: str = "owner") -> dict:
        meeting = await self._meeting(meeting_id, access)
        document = await self._document(document_id, access)
        if not self._same_project(meeting, document):
            raise MultimodalError(422, "The meeting and the document belong to different projects")
        if len(await self.store.list_links(meeting_id)) >= MAX_LINKS and await self._is_new(meeting_id, document_id):
            raise MultimodalError(422, f"At most {MAX_LINKS} documents can be attached to one meeting")
        now = self.clock()
        link, created = await self.store.add_link(Link(meeting_id=meeting_id, document_id=document_id, linked_by=linked_by, created_at=now, updated_at=now))
        if created:
            self._count("linked")
        return {"created": created, "document": self._document_view(Readable(link, document))}

    async def _is_new(self, meeting_id: str, document_id: str) -> bool:
        return all(link.document_id != document_id for link in await self.store.list_links(meeting_id))

    async def unlink(self, meeting_id: str, document_id: str, access: AccessContext) -> dict:
        """Detach a document. Its estimates, corrections and findings for THIS meeting go; the document, the meeting and every other attachment are untouched."""
        await self._meeting(meeting_id, access)
        removed = await self.store.remove_link(meeting_id, document_id)
        if not removed:
            raise MultimodalError(404, NO_SUCH_DOCUMENT)
        await self.store.drop_document(document_id, meeting_id=meeting_id)
        self._count("unlinked")
        return {"unlinked": True}

    @staticmethod
    def _document_view(r: Readable) -> dict:
        d = r.document
        return {
            "document_id": d.id, "title": d.title, "filename": d.filename, "state": d.state.value, "ready": ready(d), "page_count": d.page_count, "tier": d.tier, "sensitivity": d.sensitivity.value,
            "project_scope": d.project_scope, "link_status": r.link.link_status, "linked_at": r.link.created_at.isoformat(), "revision": revision_of(d), "error_code": d.error_code,
        }

    # -- the overview -------------------------------------------------------------------------------------------------------

    async def overview(self, meeting_id: str, access: AccessContext) -> dict:
        meeting = await self._meeting(meeting_id, access)
        docs = await self._readable(meeting_id, access)
        by_id = {r.document.id: r for r in docs}
        segs = snapshot(meeting) if meeting.transcript_segments else []
        now_windows = {w.key: w for w in windows(segs)}
        current_hash = transcript_hash(segs) if segs else None
        aligns = await self.store.list_alignments(meeting_id)
        reviews = {r.window_key: r for r in await self.store.list_reviews(meeting_id)}
        arun = await self.store.latest_run(meeting_id, RunKind.ALIGNMENT)
        nrun = await self.store.latest_run(meeting_id, RunKind.ANALYSIS)
        revisions = {d: revision_of(r.document) for d, r in by_id.items()}
        views = [self.window_view(a, reviews.get(a.window_key), now_windows.get(a.window_key), revisions, by_id) for a in aligns]
        items = [i for i in await self.store.list_items(meeting_id=meeting_id) if self._may_see(i.sensitivity, i.project_scope, access)]  # a finding that used a document above this caller's class is not listed, not counted
        arun, nrun = self._visible(arun, access), self._visible(nrun, access)
        texts = {s.index: s.text for s in segs}
        shown = {(v["shown"]["document_id"], v["shown"]["page"]) for v in views if counts_as_discussed(v["shown"], v["stale"])}
        undiscussed = [] if not aligns else [
            {"document_id": r.document.id, "document_title": r.document.title, "page": n}
            for r in docs if ready(r.document) for n in range(1, (r.document.page_count or 0) + 1) if (r.document.id, n) not in shown]
        return {
            "meeting_id": meeting_id,
            "sensitivity": self._effective_sensitivity(meeting, [r.document for r in docs]).value,
            "documents": [self._document_view(r) for r in docs],
            "transcript_hash": current_hash,
            "alignment": {"state": state_of(arun), "run": arun.view() if arun else None, "partial": self._partial(arun, sum(1 for a in aligns if a.unchecked), len(aligns)), "transcript_changed": bool(arun and current_hash and arun.transcript_hash != current_hash),
                          "documents_changed": bool(arun and any(arun.doc_revisions.get(d) not in (None, rev) for d, rev in revisions.items())),
                          "documents_added": bool(arun and any(d not in arun.doc_revisions for d in revisions if ready(by_id[d].document)))},
            "analysis": {"state": state_of(nrun), "run": nrun.view() if nrun else None, "partial": self._partial(nrun, int((nrun.stats if nrun else {}).get("chunks_failed", 0)), int((nrun.stats if nrun else {}).get("chunks", 0))), "items": [self.item_view(i, texts, revisions) for i in items]},
            "windows": views,
            "unaddressed": undiscussed,
            "disclaimer": "Which page was discussed is an estimate from the wording of the discussion. Nothing here shows what was on a screen at any time.",
        }

    @staticmethod
    def _partial(run: Run | None, missing: int, total: int) -> dict | None:
        """A finished run that could not read some parts says so: what is missing is unchecked, which is different from checked and empty."""
        return {"missing": missing, "of": total} if run is not None and run.status is RunStatus.SUCCEEDED and missing > 0 else None

    def window_view(self, a: Alignment, review: Review | None, window: align_mod.Window | None, revisions: dict[str, str], docs: dict[str, Readable]) -> dict:
        """One window as the owner sees it: Reachy's estimate, the owner's decision, and what is shown (the owner's decision wins while it is valid)."""
        source_changed = window is None or a.transcript_revision != window.revision
        document_changed = a.document_id is not None and revisions.get(a.document_id) not in (None, a.document_revision)
        usable = a.document_id is not None and a.document_id in docs
        suggestion = None
        if usable and a.page is not None:
            suggestion = {
                "document_id": a.document_id, "document_title": docs[a.document_id].document.title, "page": a.page, "locator": a.locator, "slide_title": a.slide_title,
                "certainty": a.certainty.value, "method": a.method.value, "relation": a.relation.value, "reason": a.reason, "model_note": a.model_note, "shared_terms": a.shared_terms,
                "explicit_refs": a.explicit_refs, "contradictions": [c.model_dump(mode="json") for c in a.contradictions if c.document_id in docs],
                "alternatives": [{**alt.model_dump(mode="json"), "document_title": docs[alt.document_id].document.title} for alt in a.alternatives if alt.document_id in docs],
            }
        owner = None
        status = "suggested"
        shown = None
        if suggestion is not None:
            shown = {"document_id": suggestion["document_id"], "document_title": suggestion["document_title"], "page": suggestion["page"], "locator": suggestion["locator"],
                     "slide_title": suggestion["slide_title"], "authority": "suggested", "certainty": suggestion["certainty"]}
        if review is not None:
            window_rev_ok = window is not None and review.transcript_revision == window.revision
            doc_ok = review.document_id is None or (review.document_id in docs and revisions.get(review.document_id) == review.document_revision)
            valid = window_rev_ok and doc_ok
            owner = {"decision": review.decision.value, "document_id": review.document_id, "page": review.page, "valid": valid,
                     "document_title": docs[review.document_id].document.title if review.document_id in docs else None,
                     "locator": locator(review.document_id, review.page) if review.document_id and review.page else None, "reviewed_at": review.updated_at.isoformat()}
            if not valid:
                status = "needs_revalidation"
                if review.decision in (ReviewDecision.CONFIRMED, ReviewDecision.REPLACED) and review.document_id in docs:
                    shown = {"document_id": review.document_id, "document_title": owner["document_title"], "page": review.page, "locator": owner["locator"], "slide_title": None,
                             "authority": "owner_stale", "certainty": None}
                else:
                    shown = None
            elif review.decision in (ReviewDecision.CONFIRMED, ReviewDecision.REPLACED):
                status = review.decision.value
                shown = {"document_id": review.document_id, "document_title": owner["document_title"], "page": review.page, "locator": owner["locator"],
                         "slide_title": a.slide_title if (review.document_id, review.page) == (a.document_id, a.page) else None, "authority": "owner", "certainty": None}
            elif review.decision is ReviewDecision.NO_SLIDE:
                status, shown = "no_slide", None
            elif review.decision is ReviewDecision.REMOVED:
                if suggestion is None or (suggestion["document_id"], suggestion["page"]) == (review.rejected_document_id, review.rejected_page):
                    status, shown = "removed", None
                # a different suggestion from a later run is a new proposal: it is shown as such
        return {
            "window_key": a.window_key, "segment_ids": a.segment_ids, "start": a.start, "end": a.end, "suggestion": suggestion, "owner": owner, "review_status": status, "shown": shown,
            "source_changed": source_changed, "document_changed": document_changed, "stale": source_changed or document_changed, "unchecked": a.unchecked,
        }

    @staticmethod
    def item_view(item: Item, current: dict[int, str], revisions: dict[str, str]) -> dict:
        """An item is flagged when its own quote is no longer in its own segments (a correction touched them) or its page was read from a document revision that is not current."""
        data = item.model_dump(mode="json", exclude={"fingerprint", "final_text"})
        changed = False
        for c in item.evidence:
            if c.source == "transcript":
                ids = c.segments or ([c.segment] if c.segment is not None else [])
                changed = changed or not all(n in current for n in ids) or locate(" ".join(current[n] for n in ids if n in current), c.quote) is None
        data["source_changed"] = changed
        data["document_changed"] = any(c.source == "document" and revisions.get(c.document_id or "") != c.revision for c in item.evidence)
        if item.kind is ItemKind.ACTION:
            data["task_text"] = item.final_text or default_task_text(item)
        return data

    # -- runs ---------------------------------------------------------------------------------------------------------------

    async def _prepare(self, meeting_id: str, access: AccessContext) -> tuple[Meeting, list[Readable], str]:
        meeting = await self._meeting(meeting_id, access)
        self._ready_transcript(meeting)
        segs = snapshot(meeting)
        if not segs:
            raise MultimodalError(422, "The transcript is empty")
        docs = [r for r in await self._readable(meeting_id, access) if ready(r.document)]
        if not docs:
            raise MultimodalError(409, "Attach a processed document first")
        return meeting, docs, transcript_hash(segs)

    async def enqueue_alignment(self, meeting_id: str, access: AccessContext, *, force: bool = False, expected_hash: str | None = None) -> dict:
        meeting, docs, th = await self._prepare(meeting_id, access)
        if expected_hash is not None and expected_hash != th:
            raise MultimodalError(409, "The transcript changed since you opened it; reload it")
        revisions = {r.document.id: revision_of(r.document) for r in docs}
        run = Run(meeting_id=meeting.id, kind=RunKind.ALIGNMENT, ceiling=access.sensitivity_ceiling, transcript_hash=th, doc_revisions=revisions, force=force, created_at=self.clock(),
                  inputs_hash=digest(th, *(f"{d}:{v}" for d, v in sorted(revisions.items())), ANALYSIS_VERSION))
        _, created = await self.store.enqueue(run, force=force)
        if created:
            self._count("alignment_enqueued")
            self.wake.set()
        return {"created": created, **await self.overview(meeting_id, access)}

    async def enqueue_analysis(self, meeting_id: str, access: AccessContext, *, force: bool = False) -> dict:
        """Combined analysis. It reads the page estimates, so one is made first when the current sources have none (the same idempotent request as the alignment button)."""
        meeting, docs, th = await self._prepare(meeting_id, access)
        revisions = {r.document.id: revision_of(r.document) for r in docs}
        await self.enqueue_alignment(meeting_id, access, force=False)
        reviews = await self.store.list_reviews(meeting_id)
        run = Run(meeting_id=meeting.id, kind=RunKind.ANALYSIS, ceiling=access.sensitivity_ceiling, transcript_hash=th, doc_revisions=revisions, force=force, created_at=self.clock(),
                  inputs_hash=digest(th, *(f"{d}:{v}" for d, v in sorted(revisions.items())), *(f"{r.window_key}:{r.decision.value}:{r.document_id}:{r.page}" for r in reviews), ANALYSIS_PROMPT_VERSION))
        _, created = await self.store.enqueue(run, force=force)
        if created:
            self._count("analysis_enqueued")
            self.wake.set()
        return {"created": created, **await self.overview(meeting_id, access)}

    async def retry(self, run_id: str, access: AccessContext) -> dict:
        run = await self.store.get_run(run_id)
        if run is None:
            raise MultimodalError(404, "No such run")
        await self._meeting(run.meeting_id, access)
        run, outcome = await self.store.retry_run(run_id, now=self.clock())
        if outcome == "not_failed":
            raise MultimodalError(409, "Only a failed run can be retried")
        if outcome == "active":
            raise MultimodalError(409, "This meeting is already being processed")
        self.wake.set()
        return await self.overview(run.meeting_id, access)

    async def requeue_interrupted(self) -> int:
        """Called once when this process starts its runner (there is one runner): runs the previous process left `processing` are queued again at once."""
        n = await self.store.requeue_processing()
        if n:
            self._count("requeued", n)
            self.wake.set()
        return n

    async def process_next(self) -> bool:
        """Claim and process one run. Returns whether there was one. Never raises."""
        run = await self.store.claim_next(self.clock())
        if run is None:
            return False
        started = time.monotonic()
        try:
            offered = await self.provider() if self.provider is not None else None
            if offered is None:
                raise ExtractionFailed("model_unavailable")
            ask, model = offered
            async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                await self._execute(run, ask, model, started)
            self._count(f"{run.kind.value}_succeeded")
        except ExtractionFailed as exc:
            await self._fail(run, exc.code)
        except MultimodalError as exc:
            await self._fail(run, "source_unavailable" if exc.status in (403, 404) else "source_changed")
        except TimeoutError:
            await self._fail(run, "timeout")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors can carry URLs or text: log the type only
            log.warning("multimodal run failed: %s", type(exc).__name__)
            await self._fail(run, "model_unavailable" if type(exc).__name__ == "ProviderUnavailable" else "internal_error")
        return True

    async def _fail(self, run: Run, code: str) -> None:
        self._count(f"failed_{code}")
        await self.store.fail_run(run.id, code, now=self.clock())

    async def _sources(self, run: Run) -> tuple[Meeting, list, dict[str, Deck], list[Document]]:
        """Read the sources again, with exactly the access the request had, and refuse to continue if either changed since it was queued."""
        access = access_from_ceiling(run.ceiling.value)
        meeting = await self._meeting(run.meeting_id, access)
        segs = snapshot(meeting)
        if transcript_hash(segs) != run.transcript_hash:
            raise MultimodalError(409, "source_changed")
        decks: dict[str, Deck] = {}
        documents: list[Document] = []
        linked = {link.document_id for link in await self.store.list_links(run.meeting_id)}
        for document_id, revision in run.doc_revisions.items():
            if document_id not in linked:
                raise MultimodalError(409, "source_changed")
            document = await self._document(document_id, access)
            if not ready(document) or revision_of(document) != revision:
                raise MultimodalError(409, "source_changed")
            decks[document_id] = await self.load_deck(document, access)
            documents.append(document)
        if not decks:
            raise MultimodalError(409, "source_changed")
        return meeting, segs, decks, documents

    async def _execute(self, run: Run, ask: align_mod.Ask, model: str, started: float) -> None:
        meeting, segs, decks, documents = await self._sources(run)
        level = self._effective_sensitivity(meeting, documents)
        scope = meeting.project_scope or next((d.project_scope for d in documents if d.project_scope), None)
        loaded = round((time.monotonic() - started) * 1000)
        if run.kind is RunKind.ALIGNMENT:
            result = await align_mod.align(run_id=run.id, meeting_id=meeting.id, segments=segs, decks=list(decks.values()), ask=ask, model=model, sensitivity=level, project_scope=scope)
            stats = {**result.stats, "documents": len(decks), "pages": sum(len(d.pages) for d in decks.values()), "load_ms": loaded, "elapsed_ms": round((time.monotonic() - started) * 1000)}
            await self.store.complete_alignment(run.id, result.alignments, model=model, stats=stats, now=self.clock())
            return
        arun = await self.store.latest_run(meeting.id, RunKind.ALIGNMENT)
        if arun is None or arun.status is not RunStatus.SUCCEEDED or arun.transcript_hash != run.transcript_hash or arun.doc_revisions != run.doc_revisions:
            raise ExtractionFailed("alignment_missing")  # the page estimates this analysis reads are not current: make them first
        aligns = await self.store.list_alignments(meeting.id)
        reviews = {r.window_key: r for r in await self.store.list_reviews(meeting.id)}
        win = {w.key: w for w in windows(segs)}
        docs = {d.id: Readable(Link(meeting_id=meeting.id, document_id=d.id, linked_by="owner"), d) for d in documents}
        revisions = {d.id: revision_of(d) for d in documents}
        effective: dict[str, tuple[str, int] | None] = {}
        for a in aligns:
            view = self.window_view(a, reviews.get(a.window_key), win.get(a.window_key), revisions, docs)
            effective[a.window_key] = (view["shown"]["document_id"], view["shown"]["page"]) if counts_as_discussed(view["shown"], view["stale"]) else None
        ctx = analysis_mod.Context(run_id=run.id, meeting_id=meeting.id, meeting_title=meeting.title, transcript_hash=run.transcript_hash, segments=segs, windows=list(win.values()), decks=decks,
                                   effective=effective, sensitivity=level, project_scope=scope)
        items, rejected = await analysis_mod.extract(ctx, ask, model=model)
        stats = {"documents": len(decks), "windows": len(win), "chunks": len(analysis_mod.chunks(ctx)), "chunks_failed": rejected.get("bad_model_output_chunk", 0), "found": len(items), **{f"rejected_{k}": v for k, v in rejected.items()}, "elapsed_ms": round((time.monotonic() - started) * 1000)}
        await self.store.complete_analysis(run.id, items, model=model, stats=stats, now=self.clock())

    # -- the owner's decisions ----------------------------------------------------------------------------------------------

    async def review(self, meeting_id: str, window_key: str, access: AccessContext, *, decision: str, document_id: str | None = None, page: int | None = None) -> dict:
        meeting = await self._meeting(meeting_id, access)
        self._ready_transcript(meeting)
        aligns = {a.window_key: a for a in await self.store.list_alignments(meeting_id)}
        a = aligns.get(window_key)
        window = {w.key: w for w in windows(snapshot(meeting))}.get(window_key)
        if a is None:
            raise MultimodalError(404, "No such part of the transcript")
        if window is None or window.revision != a.transcript_revision:
            raise MultimodalError(409, "The transcript changed since the pages were estimated; estimate them again")
        docs = {r.document.id: r for r in await self._readable(meeting_id, access)}
        revisions = {d: revision_of(r.document) for d, r in docs.items()}
        suggestion = (a.document_id, a.page) if a.document_id in docs and a.page is not None else None
        now = self.clock()
        base = {"meeting_id": meeting_id, "window_key": window_key, "transcript_revision": window.revision, "created_at": now, "updated_at": now}
        try:
            kind = ReviewDecision(decision)
        except ValueError:
            raise MultimodalError(422, "Unknown decision") from None
        if kind in (ReviewDecision.CONFIRMED, ReviewDecision.REPLACED):
            target = (document_id, page) if document_id is not None or page is not None else suggestion
            if target is None or target[0] is None or target[1] is None:
                raise MultimodalError(422, "Choose a document and a page")
            doc = docs.get(target[0])
            if doc is None:
                raise MultimodalError(404, NO_SUCH_DOCUMENT)
            if not ready(doc.document) or not 1 <= target[1] <= (doc.document.page_count or 0):
                raise MultimodalError(422, "That document has no such page")
            review = Review(**base, decision=ReviewDecision.CONFIRMED if target == suggestion else ReviewDecision.REPLACED, document_id=target[0], page=target[1],
                            document_revision=revisions[target[0]])
        elif kind is ReviewDecision.NO_SLIDE:
            review = Review(**base, decision=kind)
        else:
            if suggestion is None:
                raise MultimodalError(409, "There is no suggestion to remove")
            review = Review(**base, decision=kind, rejected_document_id=suggestion[0], rejected_page=suggestion[1])
        await self.store.set_review(review)
        self._count(f"review_{review.decision.value}")
        overview = await self.overview(meeting_id, access)
        return {"window": next(w for w in overview["windows"] if w["window_key"] == window_key)}

    async def clear_review(self, meeting_id: str, window_key: str, access: AccessContext) -> dict:
        await self._meeting(meeting_id, access)
        if not await self.store.clear_review(meeting_id, window_key):
            raise MultimodalError(404, "There is no decision to withdraw")
        return {"cleared": True}

    # -- questions across both sources --------------------------------------------------------------------------------------

    async def ask(self, meeting_id: str, access: AccessContext, question: str) -> dict:
        question = " ".join(question.split())
        if not 3 <= len(question) <= 500:
            raise MultimodalError(422, "Ask a question of up to 500 characters")
        started = time.monotonic()
        meeting = await self._meeting(meeting_id, access)
        self._ready_transcript(meeting)
        segs = snapshot(meeting)
        docs = [r for r in await self._readable(meeting_id, access) if ready(r.document)]
        wins = windows(segs)
        by_key = {w.key: w for w in wins}
        by_id = {r.document.id: r for r in docs}
        revisions = {d: revision_of(r.document) for d, r in by_id.items()}
        reviews = {r.window_key: r for r in await self.store.list_reviews(meeting_id)}
        aligns = await self.store.list_alignments(meeting_id)
        views = {a.window_key: self.window_view(a, reviews.get(a.window_key), by_key.get(a.window_key), revisions, by_id) for a in aligns}

        def trusted(view: dict) -> tuple[str, int, str] | None:
            """The page a window may be linked to in an answer: the owner's valid decision, or a current suggestion. Stale estimates are never used."""
            shown = view["shown"]
            if not counts_as_discussed(shown, view["stale"]):
                return None
            return shown["document_id"], shown["page"], shown["authority"]

        if ask_mod.wants_undiscussed(question):
            return self._undiscussed(meeting, docs, views, trusted, started)
        sources: dict[str, ask_mod.Source] = {}
        order: list[str] = []
        used_docs: dict[str, Document] = {}

        async def add_page(doc: Document, page_no: int, text: str) -> str:
            for s in sources.values():
                if s.kind == "document" and (s.meta["document_id"], s.meta["page"]) == (doc.id, page_no):
                    return s.id
            sid = f"D{sum(1 for s in sources.values() if s.kind == 'document') + 1}"
            sources[sid] = ask_mod.Source(sid, "document", " ".join(text.split())[:ask_mod.PAGE_EXCERPT], {
                "document_id": doc.id, "title": doc.title, "page": page_no, "locator": locator(doc.id, page_no), "source_hash": doc.source_hash, "tier": doc.tier, "revision": revision_of(doc),
                "evidence_type": "derived_extraction"})
            order.append(sid)
            used_docs[doc.id] = doc
            return sid

        def add_window(window) -> str:
            for s in sources.values():
                if s.kind == "transcript" and s.meta["window_key"] == window.key:
                    return s.id
            sid = f"T{sum(1 for s in sources.values() if s.kind == 'transcript') + 1}"
            first = window.segs[0]
            sources[sid] = ask_mod.Source(sid, "transcript", window.text[:ask_mod.TRANSCRIPT_EXCERPT], {
                "window_key": window.key, "segments": [s.index for s in window.segs], "start": window.start, "end": window.end, "speaker": first.speaker,
                "start_label": f"{int(window.start) // 60}:{int(window.start) % 60:02d}"})
            order.append(sid)
            return sid

        picked = ask_mod.relevant_windows(wins, question)
        for window in picked:
            add_window(window)
        for r in docs:
            evidence = await self.documents.evidence_for_question(r.document.id, access, question)
            for passage in evidence.passages[:3]:
                await add_page(r.document, passage.page, passage.text)
        for number in ask_mod.named_pages(question):
            for r in docs:
                if (r.document.page_count or 0) >= number:
                    content = (await self.documents.read(r.document.id, access, page_range=str(number), limit=PAGE_READ_LIMIT)).content
                    await add_page(r.document, number, _MARKER.sub("", content))
        # the stretches of the transcript estimated (or confirmed) to be about the pages retrieved, and the pages estimated for the stretches retrieved
        page_ids = {(s.meta["document_id"], s.meta["page"]): s.id for s in sources.values() if s.kind == "document"}
        for key, view in views.items():
            link = trusted(view)
            if link is None or key not in by_key:
                continue
            doc_id, page_no, _authority = link
            if (doc_id, page_no) in page_ids and sum(1 for s in sources.values() if s.kind == "transcript") < ask_mod.MAX_TRANSCRIPT + 2:
                add_window(by_key[key])
        for s in [s for s in sources.values() if s.kind == "transcript"]:
            link = trusted(views[s.meta["window_key"]]) if s.meta["window_key"] in views else None
            if link and link[0] in by_id and (link[0], link[1]) not in page_ids and len([x for x in sources.values() if x.kind == "document"]) < ask_mod.MAX_PAGES:
                content = (await self.documents.read(link[0], access, page_range=str(link[1]), limit=PAGE_READ_LIMIT)).content
                page_ids[(link[0], link[1])] = await add_page(by_id[link[0]].document, link[1], _MARKER.sub("", content))
        level = self._effective_sensitivity(meeting, list(used_docs.values()))
        if not sources:
            return self._answer(meeting, level, [], {}, ask_mod.NOTHING_FOUND if docs else f"{ask_mod.NOTHING_FOUND} {ask_mod.NO_DOCUMENTS}", abstained=True, started=started, model=None, rejected={}, views=views, by_key=by_key)
        offered = await self.provider() if self.provider is not None else None
        if offered is None:
            raise MultimodalError(503, "The local model is unavailable")
        ask, model = offered
        raw = await ask(ask_mod.build_prompt(meeting.title, [sources[i] for i in order]), ask_mod.MAX_TOKENS)
        parsed = ask_mod.parse_output(raw)
        parts, rejected = ask_mod.validate_parts(parsed, sources) if parsed else ([], {"bad_model_output": 1})
        if not parts:
            return self._answer(meeting, level, [], sources, ask_mod.FAILED, abstained=True, started=started, model=model, rejected=rejected, views=views, by_key=by_key)
        self._count("answers")
        return self._answer(meeting, level, parts, sources, None, abstained=all(p["kind"] == "unknown" for p in parts), started=started, model=model, rejected=rejected, views=views, by_key=by_key)

    def _answer(self, meeting: Meeting, level: Privacy, parts: list[dict], sources: dict, message: str | None, *, abstained: bool, started: float, model: str | None, rejected: dict,
                views: dict, by_key: dict) -> dict:
        cited = {c for p in parts for c in p["cites"]}
        used = {i: sources[i] for i in sources if i in cited}
        links = []
        windows_used = {s.meta["window_key"]: s.id for s in used.values() if s.kind == "transcript"}
        pages_used = {(s.meta["document_id"], s.meta["page"]): s.id for s in used.values() if s.kind == "document"}
        possible = []
        for key, tid in windows_used.items():
            view = views.get(key)
            if view is None or not counts_as_discussed(view["shown"], view["stale"]):
                continue
            shown = view["shown"]
            did = pages_used.get((shown["document_id"], shown["page"]))
            if did:
                links.append({"transcript": tid, "document": did, "window_key": key, "authority": shown["authority"], "certainty": shown["certainty"],
                              "meaning": "owner-confirmed" if shown["authority"] == "owner" else "Reachy's estimate, not proof of what was shown"})
            if view["suggestion"] and view["suggestion"]["contradictions"]:
                possible += [{"window_key": key, **c} for c in view["suggestion"]["contradictions"]]
        caveats = []
        if links or any(s.kind == "document" for s in used.values()) and any(s.kind == "transcript" for s in used.values()):
            caveats.append("Which page a part of the discussion was about is an estimate. It is not evidence of what was on a screen.")
        if any(s.kind == "document" for s in used.values()):
            caveats.append("Document excerpts are machine-extracted text and may contain errors; open the page to check.")
        return {
            "meeting_id": meeting.id, "answered": bool(parts) and not abstained, "abstained": abstained, "message": message, "parts": parts,
            "citations": {i: ask_mod.citation(s) for i, s in used.items()}, "associations": links, "possible_disagreements": possible, "caveats": caveats,
            "sensitivity": level.value, "model": model, "prompt_version": ASK_PROMPT_VERSION, "rejected": rejected, "latency_ms": round((time.monotonic() - started) * 1000),
        }

    def _undiscussed(self, meeting: Meeting, docs: list[Readable], views: dict, trusted, started: float) -> dict:
        shown = {(t[0], t[1]) for v in views.values() if (t := trusted(v)) is not None}
        pages = [{"title_doc": r.document.title, "page": n, "title": None} for r in docs if ready(r.document) for n in range(1, (r.document.page_count or 0) + 1) if (r.document.id, n) not in shown]
        text = ask_mod.undiscussed_answer(pages, bool(views))
        level = self._effective_sensitivity(meeting, [r.document for r in docs])
        part = {"kind": "inference", "label": ask_mod.LABEL["inference"], "text": text, "cites": [], "note": None}
        return {"meeting_id": meeting.id, "answered": bool(views), "abstained": not views, "message": None if views else text, "parts": [part] if views else [], "citations": {}, "associations": [],
                "possible_disagreements": [], "caveats": ["This comes from the page estimates only; no model was used."], "sensitivity": level.value, "model": None,
                "prompt_version": ASK_PROMPT_VERSION, "rejected": {}, "latency_ms": round((time.monotonic() - started) * 1000)}

    # -- review and commit of findings --------------------------------------------------------------------------------------

    async def _item_access(self, item: Item, access: AccessContext) -> Meeting:
        meeting = await self._meeting(item.meeting_id, access)
        if not within_ceiling(item.sensitivity, access.sensitivity_ceiling) or not scope_permits(access, item.project_scope):
            raise MultimodalError(404, "No such item")
        return meeting

    async def accept(self, item_id: str, access: AccessContext, *, text: str | None = None) -> dict:
        """Confirm an action: it becomes a task, once, with the finding as provenance."""
        now = self.clock()
        item = await self.store.get_item(item_id)
        if item is None:
            raise MultimodalError(404, "No such item")
        await self._item_access(item, access)
        if item.status is ItemStatus.ACCEPTED:
            return await self._result(item)
        if item.kind is not ItemKind.ACTION or item.status in (ItemStatus.DISMISSED, ItemStatus.NOTED):
            raise MultimodalError(409, "This item is not waiting for a decision")
        if item.status is ItemStatus.PENDING:
            final = " ".join((text if text is not None else default_task_text(item)).split())
            if not final or len(final) > MAX_TEXT:
                raise MultimodalError(422, f"The text must be between 1 and {MAX_TEXT} characters")
            level = max(item.sensitivity, classify_privacy(final), key=_RANK.__getitem__)
            edited = final != default_task_text(item)
        else:
            final, level, edited = item.final_text, item.sensitivity, item.edited
        claim = await self.store.claim_accept(item_id, text=final, sensitivity=level, edited=edited, now=now)
        if claim.outcome == "done":
            return await self._result(claim.item)
        if claim.outcome == "in_progress":
            raise MultimodalError(409, "This item is being saved; try again in a moment")
        if claim.outcome == "missing":
            raise MultimodalError(404, "No such item")
        if claim.outcome != "claimed":
            raise MultimodalError(409, "This item can no longer be accepted")
        return await self._finish(claim.item)

    async def _finish(self, item: Item) -> dict:
        record_id = action_record_id(item.id)
        if await self.tasks.get_task(record_id) is None:
            try:
                await self.tasks.add_task(item.final_text, sensitivity=item.sensitivity, project_scope=item.project_scope, record_id=record_id)
            except (psycopg.errors.UniqueViolation, ValueError):
                pass  # a concurrent finisher created it first: same id, same task
        receipt = ActionReceipt(id=str(uuid.uuid5(RECEIPT_NAMESPACE, item.id)), action_type="task.created", source_channel="web", object_type="task", object_id=record_id,
                                fields={"Task": item.final_text, "From": "reviewed meeting and document action"}, notify=False)
        try:
            await self.planner.add_receipt(receipt)
        except psycopg.errors.UniqueViolation:
            pass
        except Exception:
            log.exception("could not record the receipt for an accepted meeting action")
        done = await self.store.finish_accept(item.id, "task", record_id, now=self.clock())
        if done is None:
            raise MultimodalError(409, "This item can no longer be accepted")
        self._count("accepted")
        return await self._result(done)

    async def _result(self, item: Item) -> dict:
        return {"item": self.item_view(item, {}, {}), "record": {"kind": item.record_kind, "id": item.record_id} if item.record_id else None}

    async def dismiss(self, item_id: str, access: AccessContext) -> dict:
        item = await self.store.get_item(item_id)
        if item is None:
            raise MultimodalError(404, "No such item")
        await self._item_access(item, access)
        decision = await self.store.dismiss(item_id, now=self.clock())
        if decision.outcome == "missing":
            raise MultimodalError(404, "No such item")
        if decision.outcome == "closed":
            raise MultimodalError(409, "This item was already decided")
        return await self._result(decision.item)

    # -- lifecycle ----------------------------------------------------------------------------------------------------------

    async def meeting_deleted(self, meeting_id: str) -> None:
        with contextlib.suppress(Exception):
            await self.store.drop_meeting(meeting_id)

    async def document_deleted(self, document_id: str) -> None:
        """A document is being deleted (it is already unusable): every association, estimate, correction and finding that used it is removed at once, in every meeting."""
        with contextlib.suppress(Exception):
            await self.store.drop_document(document_id)

    async def reconcile(self) -> int:
        """Finish accepts a crash interrupted: take over each stale `accepting` item and run the same idempotent finish."""
        n = 0
        for item_id in await self.store.stale_accepting(self.clock()):
            item = await self.store.get_item(item_id)
            if item is None:
                continue
            with contextlib.suppress(MultimodalError):
                await self.accept(item_id, access_from_ceiling(Privacy.SENSITIVE.value))
                n += 1
        return n

    def summary(self) -> dict[str, int]:
        return dict(self.counters)


def default_task_text(item: Item) -> str:
    text = item.text
    if item.assignee:
        text = f"{item.assignee}: {text}"
    if item.stated_time and item.stated_time.casefold() not in text.casefold():
        text = f"{text} ({item.stated_time})"
    return text[:MAX_TEXT]


__all__ = ["OPEN_ITEMS", "Certainty", "MeetingMultimodalService", "MultimodalError", "enabled"]
