"""The indexing worker (Phase 44B): turns outbox events into index rows, and reconciles the index with the stores.

A sync reads the source's *current* state, compares each item's version with the index and writes only what changed (embedding only
changed text). Everything is idempotent, so a crash at any point, a duplicate event or a replay simply converges. Embedding runs in a
thread so it never blocks the event loop the voice and chat paths share, in small batches, and the worker yields between them.

Indexing is off unless KNOWLEDGE_INDEXING_ENABLED is set; nothing here searches or returns knowledge.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from companion_core.knowledge.index import IndexRow, KnowledgeIndex
from companion_core.knowledge.outbox import Outbox, OutboxItem
from companion_core.knowledge.sources import SourceAdapter

log = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], list[list[float]]]
EMBED_BATCH = 16


def safe_reason(exc: BaseException) -> str:
    """Describe a failure without quoting it. An exception message can carry the content being indexed (a database error names the
    failing row), and this text is stored in the outbox and logged, so only the class, the database error code and the code location
    are kept."""
    parts = [type(exc).__name__]
    code = getattr(exc, "sqlstate", None)
    if code:
        parts.append(f"sqlstate {code}")
    frames = traceback.extract_tb(exc.__traceback__)
    if frames:
        last = frames[-1]
        parts.append(f"at {last.filename.rsplit('/', 1)[-1]}:{last.lineno}")
    return " ".join(parts)


@dataclass
class SyncResult:
    upserted: int = 0
    deleted: int = 0
    unchanged: int = 0


@dataclass
class WorkResult:
    processed: int = 0
    upserted: int = 0
    deleted: int = 0
    failed: int = 0
    requeued: int = 0  # changed while being worked; will run again


@dataclass
class ReconcileReport:
    sources_checked: int = 0
    enqueued: int = 0  # missing, stale or re-embedded sources handed back to the outbox
    orphans_deleted: int = 0  # index rows whose source no longer produces them


class IndexingWorker:
    def __init__(
        self,
        *,
        adapters: dict[str, SourceAdapter],
        index: KnowledgeIndex,
        outbox: Outbox,
        embed_fn: EmbedFn,
        embedding_model: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        batch: int = 10,
        lease_seconds: int = 300,
    ) -> None:
        self.adapters, self.index, self.outbox = adapters, index, outbox
        self.embed_fn, self.embedding_model, self.clock = embed_fn, embedding_model, clock
        self.batch, self.lease_seconds = batch, lease_seconds

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            vectors.extend(await asyncio.to_thread(self.embed_fn, texts[start : start + EMBED_BATCH]))
            await asyncio.sleep(0)  # let a voice turn or a chat request run between batches
        return vectors

    async def sync_source(self, source_type: str, source_id: str) -> SyncResult:
        """Make the index agree with the source as it is now."""
        adapter = self.adapters.get(source_type)
        if adapter is None:
            raise ValueError(f"no adapter for source type {source_type!r}")
        state = await adapter.state(source_id)
        if state.status != "visible":
            return SyncResult(deleted=await self.index.delete_source(source_type, source_id))
        existing = await self.index.rows_for_source(source_type, source_id)
        now = self.clock()
        wanted = {item.ref.key: item for item in state.items}
        changed = [
            item for key, item in wanted.items()
            if key not in existing or existing[key].source_version != item.version()
            or existing[key].embedding_model != self.embedding_model
        ]
        stale = [key for key in existing if key not in wanted]
        vectors = await self._embed([item.match_text for item in changed]) if changed else []
        await self.index.upsert([IndexRow.from_indexable(i, embedding_model=self.embedding_model, now=now) for i in changed], vectors)
        await self.index.delete_keys(stale)
        return SyncResult(upserted=len(changed), deleted=len(stale), unchanged=len(wanted) - len(changed))

    async def run_once(self) -> WorkResult:
        """Claim a batch from the outbox and sync each source. A failure is recorded against its row and never stops the others."""
        result = WorkResult()
        for item in await self.outbox.claim(self.clock(), lease_seconds=self.lease_seconds, limit=self.batch):
            result.processed += 1
            try:
                done = await self.sync_source(item.source_type, item.source_id)
            except Exception as exc:  # noqa: BLE001  one failing source must not stop the others; it is recorded on its own row
                reason = safe_reason(exc)
                log.error("knowledge sync failed for %s:%s: %s", item.source_type, item.source_id, reason)
                await self.outbox.fail(item, self.clock(), reason)
                result.failed += 1
                continue
            result.upserted += done.upserted
            result.deleted += done.deleted
            if not await self.outbox.complete(item, self.clock()):
                result.requeued += 1
        return result

    async def drain(self, *, max_rounds: int = 1000) -> WorkResult:
        """Run until the outbox has nothing ready (used by tests and by a first full build)."""
        total = WorkResult()
        for _ in range(max_rounds):
            step = await self.run_once()
            if not step.processed:
                break
            for name in ("processed", "upserted", "deleted", "failed", "requeued"):
                setattr(total, name, getattr(total, name) + getattr(step, name))
        return total

    async def reconcile(self) -> ReconcileReport:
        """Find drift the events did not cover (a missed trigger, a restored backup, a changed embedding model, the passage of time
        for expiry) by comparing the stores with the index, and repair it through the same outbox."""
        report = ReconcileReport()
        now = self.clock()
        seen: set[tuple[str, str]] = set()
        for source_type, adapter in self.adapters.items():
            for source_id in await adapter.list_ids():
                seen.add((source_type, source_id))
                report.sources_checked += 1
                state = await adapter.state(source_id)
                existing = await self.index.rows_for_source(source_type, source_id)
                if state.status != "visible":
                    drifted = bool(existing)
                else:
                    wanted = {i.ref.key: i for i in state.items}
                    drifted = set(wanted) != set(existing) or any(
                        existing[k].source_version != i.version() or existing[k].embedding_model != self.embedding_model
                        for k, i in wanted.items()
                    )
                if drifted:
                    await self.outbox.enqueue(source_type, source_id, now)
                    report.enqueued += 1
        for source_type, source_id in await self.index.source_ids():
            if (source_type, source_id) not in seen:
                report.orphans_deleted += await self.index.delete_source(source_type, source_id)
        return report

    async def loop(self, *, interval: float = 5.0, reconcile_every: float = 3600.0) -> None:
        """Background task: work the outbox, reconcile once at start and then on a schedule."""
        last_reconcile = float("-inf")
        loop = asyncio.get_running_loop()
        while True:
            try:
                if loop.time() - last_reconcile >= reconcile_every:
                    report = await self.reconcile()
                    last_reconcile = loop.time()
                    log.info("knowledge reconcile: %s", report)
                step = await self.run_once()
                if step.processed:
                    log.info("knowledge sync: %s", step)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("knowledge indexing loop error")
            await asyncio.sleep(interval)  # a cancellation here must propagate, or the task could never be stopped


__all__ = ["IndexingWorker", "OutboxItem", "ReconcileReport", "SyncResult", "WorkResult"]
