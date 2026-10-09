"""Read-only validation of the production knowledge index, run inside a throwaway container from the production core image
(started by `tools/knowledge_indexing_trial.py verify`). Writes nothing: no outbox enqueue, no upsert.

Checks the index against the authoritative stores through the same source adapters the worker uses (missing, extra, stale version, wrong embedding model,
orphan sources, embedding width), then runs retrieval-time revalidation for the owner on a private channel and for a shared speaker, without exposing anything
to the assistant (the library is called here only)."""

import asyncio
import os

from companion_core.knowledge.index import PostgresKnowledgeIndex
from companion_core.knowledge.retrieval import B1A, Retriever
from companion_core.knowledge.search import PostgresSearch
from companion_core.knowledge.sources import build_adapters
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.semantic.access import access_for_owner
from companion_core.tasks.postgres_store import PostgresTaskStore

from shared.database import DatabaseManager

MODEL = "sentence-transformers/all-MiniLM-L6-v2"


async def main() -> None:
    db = await DatabaseManager(os.environ["DATABASE_URL"], vector=True, min_size=1, max_size=2).start()
    adapters = build_adapters(memory=await PostgresMemoryStore.connect(db), documents=await PostgresDocumentStore.connect(db),
                              meetings=await PostgresMeetingStore.connect(db), planner=await PostgresPlannerStore.connect(db), tasks=await PostgresTaskStore.connect(db))
    index = await PostgresKnowledgeIndex.connect(db)
    expected = missing = extra = stale = wrong_model = sources = 0
    seen = set()
    by_kind: dict[str, int] = {}
    for source_type, adapter in adapters.items():
        ids = await adapter.list_ids()
        print(f"source type {source_type}: {len(ids)} sources")
        for source_id in ids:
            seen.add((source_type, source_id))
            sources += 1
            state = await adapter.state(source_id)
            existing = await index.rows_for_source(source_type, source_id)
            if state.status != "visible":
                extra += len(existing)
                continue
            wanted = {i.ref.key: i for i in state.items}
            expected += len(wanted)
            missing += len(set(wanted) - set(existing))
            extra += len(set(existing) - set(wanted))
            for key, item in wanted.items():
                by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
                if key in existing:
                    stale += existing[key].source_version != item.version()
                    wrong_model += existing[key].embedding_model != MODEL
    orphans = [s for s in await index.source_ids() if s not in seen]
    print(f"DRIFT sources={sources} expected_rows={expected} indexed={await index.count()} missing={missing} extra={extra} stale_version={stale} wrong_model={wrong_model} orphan_sources={len(orphans)}")
    print("EXPECTED_BY_KIND", dict(sorted(by_kind.items())))
    async with db.pool.connection() as conn:
        width = await (await conn.execute("SELECT count(*), min(vector_dims(embedding)), max(vector_dims(embedding)) FROM knowledge_items")).fetchone()
    print(f"EMBEDDINGS rows={width[0]} min_dims={width[1]} max_dims={width[2]}")
    search = PostgresSearch(db.pool)
    for label, access in (("owner-private", access_for_owner("owner", channel_private=True)), ("shared-speaker", access_for_owner("owner", channel_private=False))):
        r = await Retriever(search=search, adapters=adapters, config=B1A).retrieve("what did we decide", access)
        print(f"REVALIDATION {label}: returned={len(r.bundle.items)} dropped={r.bundle.dropped} max_sensitivity={r.bundle.max_sensitivity}")


asyncio.run(main())
