"""Phase 53 stores: links, runs, alignments, the owner's reviews and combined-analysis items. The in-memory twin has the same states and guarantees as the PostgreSQL store
(postgres_store.py); both follow Phase 31's store. Nothing here holds a transcript or a document's text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from companion_core.meeting_multimodal.models import (
    ACCEPTING_STALE_SECONDS,
    ACTIVE_RUNS,
    LEASE_SECONDS,
    Alignment,
    Item,
    ItemStatus,
    Link,
    Review,
    Run,
    RunKind,
    RunStatus,
    same_item,
)
from shared.models.response import Privacy


@dataclass(frozen=True)
class Claim:
    outcome: str  # claimed | in_progress | done | closed | missing
    item: Item | None = None


@dataclass(frozen=True)
class Decision:
    outcome: str  # done | already | closed | missing
    item: Item | None = None


class MultimodalStore(Protocol):
    async def add_link(self, link: Link) -> tuple[Link, bool]: ...
    async def remove_link(self, meeting_id: str, document_id: str) -> bool: ...
    async def list_links(self, meeting_id: str) -> list[Link]: ...
    async def enqueue(self, run: Run, *, force: bool) -> tuple[Run, bool]: ...
    async def get_run(self, run_id: str) -> Run | None: ...
    async def latest_run(self, meeting_id: str, kind: RunKind) -> Run | None: ...
    async def claim_next(self, now: datetime) -> Run | None: ...
    async def requeue_processing(self) -> int: ...
    async def complete_alignment(self, run_id: str, alignments: list[Alignment], *, model: str, stats: dict, now: datetime) -> int: ...
    async def complete_analysis(self, run_id: str, items: list[Item], *, model: str, stats: dict, now: datetime) -> int: ...
    async def fail_run(self, run_id: str, error: str, *, now: datetime) -> None: ...
    async def retry_run(self, run_id: str, *, now: datetime) -> tuple[Run | None, str]: ...
    async def list_alignments(self, meeting_id: str) -> list[Alignment]: ...
    async def set_review(self, review: Review) -> Review: ...
    async def clear_review(self, meeting_id: str, window_key: str) -> bool: ...
    async def list_reviews(self, meeting_id: str) -> list[Review]: ...
    async def list_items(self, *, meeting_id: str | None = None, statuses: tuple[ItemStatus, ...] | None = None) -> list[Item]: ...
    async def get_item(self, item_id: str) -> Item | None: ...
    async def item_for_record(self, record_id: str) -> Item | None: ...
    async def claim_accept(self, item_id: str, *, text: str, sensitivity: Privacy, edited: bool, now: datetime) -> Claim: ...
    async def finish_accept(self, item_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Item | None: ...
    async def dismiss(self, item_id: str, *, now: datetime) -> Decision: ...
    async def stale_accepting(self, now: datetime) -> list[str]: ...
    async def drop_meeting(self, meeting_id: str) -> int: ...
    async def drop_document(self, document_id: str, *, meeting_id: str | None = None) -> int: ...
    async def close(self) -> None: ...


OPEN_ITEMS = (ItemStatus.PENDING, ItemStatus.ACCEPTING)


def merge_items(held: list[Item], new: list[Item]) -> tuple[list[Item], list[tuple[Item, Item]]]:
    """(items to insert, (existing, fresh) pairs to refresh). A finding already extracted, accepted or dismissed is never brought back by a re-analysis, however it is worded; one the owner
    has not decided is refreshed from the newer run, so its evidence matches the sources as they read now."""
    insert: list[Item] = []
    refresh: list[tuple[Item, Item]] = []
    known = list(held)
    for item in new:
        match = next((h for h in known if h.fingerprint == item.fingerprint or same_item(h, item)), None)
        if match is None:
            insert.append(item)
            known.append(item)
        elif match.status in (ItemStatus.PENDING, ItemStatus.NOTED):
            refresh.append((match, item))
    return insert, refresh


def strip_document(item: Item, document_id: str) -> Item | None:
    """What is left of an item when a document is deleted: nothing, unless it was already confirmed (its action became a task), in which case only the document's quotes go."""
    kept = [c for c in item.evidence if not (c.source == "document" and c.document_id == document_id)]
    if len(kept) == len(item.evidence):
        return item
    if item.status is ItemStatus.ACCEPTED and kept:
        return item.model_copy(update={"evidence": kept})
    return None


class InMemoryMultimodalStore:
    def __init__(self) -> None:
        self._links: dict[tuple[str, str], Link] = {}
        self._runs: dict[str, Run] = {}
        self._alignments: dict[str, dict[str, Alignment]] = {}
        self._reviews: dict[tuple[str, str], Review] = {}
        self._items: dict[str, Item] = {}

    # -- links --------------------------------------------------------------------------------------------------------------

    async def add_link(self, link: Link) -> tuple[Link, bool]:
        key = (link.meeting_id, link.document_id)
        if key in self._links:
            return self._links[key], False
        self._links[key] = link
        return link, True

    async def remove_link(self, meeting_id: str, document_id: str) -> bool:
        return self._links.pop((meeting_id, document_id), None) is not None

    async def list_links(self, meeting_id: str) -> list[Link]:
        return sorted((link for (m, _), link in self._links.items() if m == meeting_id), key=lambda link: (link.created_at, link.document_id))

    # -- runs ---------------------------------------------------------------------------------------------------------------

    async def enqueue(self, run: Run, *, force: bool) -> tuple[Run, bool]:
        for existing in self._runs.values():
            if existing.meeting_id == run.meeting_id and existing.kind is run.kind and existing.status in ACTIVE_RUNS:
                return existing, False
        if not force:
            for existing in self._runs.values():
                if existing.meeting_id == run.meeting_id and existing.kind is run.kind and existing.inputs_hash == run.inputs_hash and existing.status is RunStatus.SUCCEEDED:
                    return existing, False
        self._runs[run.id] = run
        return run, True

    async def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    async def latest_run(self, meeting_id: str, kind: RunKind) -> Run | None:
        runs = [r for r in self._runs.values() if r.meeting_id == meeting_id and r.kind is kind]
        return max(reversed(runs), key=lambda r: r.created_at, default=None)

    async def claim_next(self, now: datetime) -> Run | None:
        ready = [r for r in self._runs.values() if r.status is RunStatus.QUEUED or (r.status is RunStatus.PROCESSING and r.lease_until is not None and r.lease_until <= now)]
        if not ready:
            return None
        run = min(ready, key=lambda r: r.created_at)
        self._runs[run.id] = claimed = run.model_copy(update={"status": RunStatus.PROCESSING, "attempts": run.attempts + 1, "started_at": now, "lease_until": now + timedelta(seconds=LEASE_SECONDS)})
        return claimed

    def _finish(self, run: Run, model: str, stats: dict, now: datetime) -> None:
        self._runs[run.id] = run.model_copy(update={"status": RunStatus.SUCCEEDED, "model": model, "stats": stats, "finished_at": now, "lease_until": None, "error": None})

    async def requeue_processing(self) -> int:
        """At startup of the one process that runs these: a run left `processing` belongs to a process that no longer exists, so it is queued again now instead of after its lease."""
        n = 0
        for key, r in list(self._runs.items()):
            if r.status is RunStatus.PROCESSING:
                self._runs[key] = r.model_copy(update={"status": RunStatus.QUEUED, "lease_until": None})
                n += 1
        return n

    async def complete_alignment(self, run_id: str, alignments: list[Alignment], *, model: str, stats: dict, now: datetime) -> int:
        run = self._runs.get(run_id)
        if run is None or run.status is not RunStatus.PROCESSING:
            return 0
        self._alignments[run.meeting_id] = {a.window_key: a for a in alignments}  # one current estimate per window: the previous run's rows are replaced, the owner's reviews are not touched
        self._finish(run, model, stats, now)
        return len(alignments)

    async def complete_analysis(self, run_id: str, items: list[Item], *, model: str, stats: dict, now: datetime) -> int:
        run = self._runs.get(run_id)
        if run is None or run.status is not RunStatus.PROCESSING:
            return 0
        held = [i for i in self._items.values() if i.meeting_id == run.meeting_id]
        insert, refresh = merge_items(held, items)
        for match, fresh in refresh:
            self._items[match.id] = match.model_copy(update={
                "run_id": fresh.run_id, "transcript_hash": fresh.transcript_hash, "text": fresh.text, "evidence": fresh.evidence, "assignee": fresh.assignee, "stated_time": fresh.stated_time,
                "ambiguity": fresh.ambiguity, "support": fresh.support, "model": fresh.model, "prompt_version": fresh.prompt_version, "sensitivity": fresh.sensitivity})
        for item in insert:
            self._items[item.id] = item
        self._finish(run, model, {**stats, "items": len(insert)}, now)
        return len(insert)

    async def fail_run(self, run_id: str, error: str, *, now: datetime) -> None:
        run = self._runs.get(run_id)
        if run is not None and run.status is RunStatus.PROCESSING:
            self._runs[run_id] = run.model_copy(update={"status": RunStatus.FAILED, "error": error, "finished_at": now, "lease_until": None})

    async def retry_run(self, run_id: str, *, now: datetime) -> tuple[Run | None, str]:
        run = self._runs.get(run_id)
        if run is None:
            return None, "missing"
        if run.status is not RunStatus.FAILED:
            return run, "not_failed"
        if any(r.meeting_id == run.meeting_id and r.kind is run.kind and r.status in ACTIVE_RUNS for r in self._runs.values()):
            return run, "active"
        self._runs[run_id] = queued = run.model_copy(update={"status": RunStatus.QUEUED, "error": None, "finished_at": None})
        return queued, "queued"

    # -- alignments and reviews ---------------------------------------------------------------------------------------------

    async def list_alignments(self, meeting_id: str) -> list[Alignment]:
        return sorted(self._alignments.get(meeting_id, {}).values(), key=lambda a: (a.start, a.window_key))

    async def set_review(self, review: Review) -> Review:
        held = self._reviews.get((review.meeting_id, review.window_key))
        stored = review.model_copy(update={"created_at": held.created_at}) if held else review
        self._reviews[(review.meeting_id, review.window_key)] = stored
        return stored

    async def clear_review(self, meeting_id: str, window_key: str) -> bool:
        return self._reviews.pop((meeting_id, window_key), None) is not None

    async def list_reviews(self, meeting_id: str) -> list[Review]:
        return sorted((r for (m, _), r in self._reviews.items() if m == meeting_id), key=lambda r: r.window_key)

    # -- items --------------------------------------------------------------------------------------------------------------

    async def list_items(self, *, meeting_id: str | None = None, statuses: tuple[ItemStatus, ...] | None = None) -> list[Item]:
        rows = [i for i in self._items.values() if (meeting_id is None or i.meeting_id == meeting_id) and (statuses is None or i.status in statuses)]
        return sorted(rows, key=lambda i: (i.evidence[0].start or 0.0, i.created_at, i.kind.value))

    async def get_item(self, item_id: str) -> Item | None:
        return self._items.get(item_id)

    async def item_for_record(self, record_id: str) -> Item | None:
        return next((i for i in self._items.values() if i.record_id == record_id), None)

    async def claim_accept(self, item_id: str, *, text: str, sensitivity: Privacy, edited: bool, now: datetime) -> Claim:
        i = self._items.get(item_id)
        if i is None:
            return Claim("missing")
        if i.status is ItemStatus.ACCEPTED:
            return Claim("done", i)
        if i.status is ItemStatus.ACCEPTING:
            if i.accepting_at is not None and (now - i.accepting_at).total_seconds() < ACCEPTING_STALE_SECONDS:
                return Claim("in_progress", i)
            self._items[item_id] = i = i.model_copy(update={"accepting_at": now})
            return Claim("claimed", i)
        if i.status is not ItemStatus.PENDING:
            return Claim("closed", i)
        self._items[item_id] = i = i.model_copy(update={"status": ItemStatus.ACCEPTING, "final_text": text, "sensitivity": sensitivity, "edited": edited, "accepting_at": now})
        return Claim("claimed", i)

    async def finish_accept(self, item_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Item | None:
        i = self._items.get(item_id)
        if i is None:
            return None
        if i.status is ItemStatus.ACCEPTED:
            return i
        if i.status is not ItemStatus.ACCEPTING:
            return None
        self._items[item_id] = done = i.model_copy(update={"status": ItemStatus.ACCEPTED, "record_kind": record_kind, "record_id": record_id, "decided_at": now})
        return done

    async def dismiss(self, item_id: str, *, now: datetime) -> Decision:
        i = self._items.get(item_id)
        if i is None:
            return Decision("missing")
        if i.status is ItemStatus.DISMISSED:
            return Decision("already", i)
        if i.status not in (ItemStatus.PENDING, ItemStatus.NOTED):
            return Decision("closed", i)
        self._items[item_id] = done = i.model_copy(update={"status": ItemStatus.DISMISSED, "decided_at": now})
        return Decision("done", done)

    async def stale_accepting(self, now: datetime) -> list[str]:
        return [i.id for i in self._items.values() if i.status is ItemStatus.ACCEPTING and (i.accepting_at is None or (now - i.accepting_at).total_seconds() >= ACCEPTING_STALE_SECONDS)]

    # -- lifecycle ----------------------------------------------------------------------------------------------------------

    async def drop_meeting(self, meeting_id: str) -> int:
        """The meeting is gone: its links, runs, estimates, reviews and findings go with it. A task already made from an action stays (it is the owner's record)."""
        n = sum(1 for (m, _) in self._links if m == meeting_id)
        self._links = {k: v for k, v in self._links.items() if k[0] != meeting_id}
        self._runs = {k: r for k, r in self._runs.items() if r.meeting_id != meeting_id}
        n += len(self._alignments.pop(meeting_id, {}))
        self._reviews = {k: r for k, r in self._reviews.items() if k[0] != meeting_id}
        gone = [k for k, i in self._items.items() if i.meeting_id == meeting_id]
        for k in gone:
            del self._items[k]
        return n + len(gone)

    async def drop_document(self, document_id: str, *, meeting_id: str | None = None) -> int:
        """The document is gone or is being deleted (every meeting), or one attachment was removed (`meeting_id`): every association, estimate, review and finding that depends on it goes; everything
        else (the meeting, other documents, the document itself) is untouched."""

        def mine(m: str) -> bool:
            return meeting_id is None or m == meeting_id

        n = 0
        for key in [k for k in self._links if k[1] == document_id and mine(k[0])]:
            del self._links[key]
            n += 1
        for m, rows in self._alignments.items():
            if not mine(m):
                continue
            for window_key, a in list(rows.items()):
                if a.document_id == document_id:
                    del rows[window_key]
                    n += 1
                elif any(alt.document_id == document_id for alt in a.alternatives):
                    rows[window_key] = a.model_copy(update={"alternatives": [alt for alt in a.alternatives if alt.document_id != document_id]})
        for key, r in list(self._reviews.items()):
            if mine(key[0]) and document_id in (r.document_id, r.rejected_document_id):
                del self._reviews[key]
                n += 1
        for key, i in list(self._items.items()):
            if mine(i.meeting_id) and document_id in i.document_ids():
                kept = strip_document(i, document_id)
                if kept is None:
                    del self._items[key]
                else:
                    self._items[key] = kept
                n += 1
        for key, r in list(self._runs.items()):
            if mine(r.meeting_id) and document_id in r.doc_revisions:
                self._runs[key] = r.model_copy(update={"doc_revisions": {d: v for d, v in r.doc_revisions.items() if d != document_id}})
        return n

    async def close(self) -> None:
        return None
