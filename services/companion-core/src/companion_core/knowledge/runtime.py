"""Starting the indexing worker inside core (Phase 44B). Off unless KNOWLEDGE_INDEXING_ENABLED is true: with it off nothing is built, no
embedding model is loaded and no table is read. Even on, nothing searches or returns knowledge; that is a later stage behind its own
flags."""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass

from companion_core.knowledge.index import PostgresKnowledgeIndex
from companion_core.knowledge.outbox import PostgresOutbox
from companion_core.knowledge.sources import build_adapters
from companion_core.knowledge.worker import IndexingWorker


def indexing_enabled() -> bool:
    return os.environ.get("KNOWLEDGE_INDEXING_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class IndexingHandle:
    task: asyncio.Task
    worker: IndexingWorker
    _close: list

    async def stop(self) -> None:
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task
        for closer in self._close:
            await closer()


async def start_indexing(
    *, dsn: str, memory, documents, meetings, planner, tasks, embed_fn=None, embedding_model=None,
    interval: float = 5.0, reconcile_every: float = 3600.0,
) -> IndexingHandle:
    if embed_fn is None:
        from companion_core.rag import embeddings

        embed_fn, embedding_model = embeddings.embed, embeddings._MODEL_NAME
        # Indexing is background work that shares the host with speech and language models: by default torch gets two threads, not
        # every core. (Measured on the development host: 2 threads embedded faster than 14 and left the event loop free; see
        # docs/verification/phase-44b-2026-10-08.md.)
        import torch

        torch.set_num_threads(max(1, int(os.environ.get("KNOWLEDGE_EMBED_THREADS", "2"))))
    index, outbox = await PostgresKnowledgeIndex.connect(dsn), await PostgresOutbox.connect(dsn)
    worker = IndexingWorker(
        adapters=build_adapters(memory=memory, documents=documents, meetings=meetings, planner=planner, tasks=tasks),
        index=index, outbox=outbox, embed_fn=embed_fn, embedding_model=embedding_model or "unknown",
    )
    task = asyncio.create_task(worker.loop(interval=interval, reconcile_every=reconcile_every))
    return IndexingHandle(task, worker, [index.close, outbox.close])
