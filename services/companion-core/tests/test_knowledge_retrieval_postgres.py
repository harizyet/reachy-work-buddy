"""Phase 44D on real Postgres (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector): the SQL behind lexical and vector
search, the access pre-filters, and the whole pipeline over the real stores and a populated index."""

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from companion_core.knowledge.index import IndexRow, PostgresKnowledgeIndex
from companion_core.knowledge.outbox import PostgresOutbox
from companion_core.knowledge.retrieval import B1A, B1B, Retriever
from companion_core.knowledge.search import PostgresSearch, build_filter
from companion_core.knowledge.sources import build_adapters
from companion_core.knowledge.worker import IndexingWorker
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.migrations.__main__ import upgrade
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.secrets import Keyring
from companion_core.semantic import access
from companion_core.semantic.model import AccessContext, SourceFilters
from companion_core.tasks.postgres_store import PostgresTaskStore
from psycopg.types.json import Json

from shared.models.response import Privacy

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector"
)
KEYS = Keyring("one", {"one": b"\x01" * 32})
NOW = datetime.now(UTC)


def embed(texts):
    out = []
    for text in texts:
        vector = [0.0] * 384
        for word in text.lower().split():
            vector[int(hashlib.md5(word.strip(".,:").encode()).hexdigest(), 16) % 384] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        out.append([v / norm for v in vector] if norm else vector)
    return out


@pytest.fixture
def dsn():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    url = psycopg.conninfo.make_conninfo(root, dbname=name)
    upgrade(url, KEYS)
    try:
        yield url
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def ctx(**kw):
    return AccessContext(**{"principal": "o", "sensitivity_ceiling": Privacy.WORK_PRIVATE, **kw})


def row(key, text, *, sensitivity=Privacy.WORK_PRIVATE, scope=None, local_only=False, valid_until=None, kind="note"):
    source_type, _, rest = key.partition(":")
    source_id, _, locator = rest.partition("#")
    return IndexRow(ref_key=key, source_type=source_type, source_id=source_id, locator=locator or None, kind=kind, source_version="v",
                    match_text=text, sensitivity=sensitivity, project_scope=scope, local_only=local_only, confidence=1.0,
                    observed_at=None, valid_from=None, valid_until=valid_until, embedding_model="t", indexed_at=NOW)


def test_lexical_and_vector_sql_rank_filter_and_survive_hostile_text(dsn):
    async def go():
        index, search = await PostgresKnowledgeIndex.connect(dsn), None
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        search = PostgresSearch(pool)
        rows = [
            row("note:a", "the retry limit for failed jobs is five"),
            row("note:b", "falcon runs on the gpu host"),
            row("note:c", "retry retry retry limit limit"),
            row("note:secret", "retry limit for the payroll job", sensitivity=Privacy.SENSITIVE),
            row("note:lantern", "retry policy for lantern deploys", scope="lantern"),
            row("meeting:m#3", "Priya: the retry limit is five", local_only=True, kind="meeting_segment"),
            row("note:old", "retry limit was three", valid_until=NOW - timedelta(days=1)),
        ]
        await index.upsert(rows, embed([r.match_text for r in rows]))
        flt = build_filter(ctx(), None, temporal="current")
        lex = await search.lexical("what is the retry limit?", flt, 10)
        keys = [h.ref_key for h in lex]
        assert keys[0] in ("note:c", "note:a", "meeting:m#3") and "note:b" not in keys  # falcon has no query word
        assert "note:secret" not in keys and "note:old" not in keys  # over the ceiling; lapsed
        assert all(h.score > 0 for h in lex) and len(keys) == len(set(keys))
        assert [h.ref_key for h in await search.lexical("retry", build_filter(ctx(sensitivity_ceiling=Privacy.SENSITIVE), None, temporal="current"), 10)].count("note:secret") == 1
        assert "note:lantern" not in [h.ref_key for h in await search.lexical("retry", build_filter(ctx(project_scopes=frozenset({"harbor"})), None, temporal="current"), 10)]
        assert "note:lantern" in [h.ref_key for h in await search.lexical("retry", build_filter(ctx(project_scopes=frozenset({"lantern"})), None, temporal="current"), 10)]
        cloud = [h.ref_key for h in await search.lexical("retry limit", build_filter(ctx(destinations=frozenset({"cloud"})), None, temporal="current"), 10)]
        assert "meeting:m#3" not in cloud and "note:a" in cloud
        hist = [h.ref_key for h in await search.lexical("retry limit three", build_filter(ctx(), None, temporal="include_historical"), 10)]
        assert "note:old" in hist
        only_meetings = await search.lexical("retry", build_filter(ctx(), SourceFilters(source_types=frozenset({"meeting"})), temporal="current"), 10)
        assert [h.ref_key for h in only_meetings] == ["meeting:m#3"]
        pinned = await search.lexical("retry", build_filter(ctx(), SourceFilters(pinned_sources=frozenset({("note", "c")})), temporal="current", pinned_only=True), 10)
        assert [h.ref_key for h in pinned] == ["note:c"]

        assert await search.lexical("the of and", flt, 10) == [] and await search.lexical("", flt, 10) == []
        for hostile in ("'; DROP TABLE knowledge_items; --", "retry & | ! ( ) : * <-> falcon", "retry\\x00", "%s %(x)s {}", "x" * 4000):
            await search.lexical(hostile, flt, 5)  # must not raise, must not alter anything
        assert await index.count() == len(rows)

        vec = await search.vector(embed(["falcon gpu host"])[0], flt, 3)
        assert vec[0].ref_key == "note:b" and 0.0 < vec[0].score <= 1.0001
        assert "note:secret" not in [h.ref_key for h in vec]
        assert [h.ref_key for h in await search.vector(embed(["falcon gpu host"])[0], build_filter(ctx(), None, temporal="current"), 100)] != []
        # a filter that excludes nearly everything still returns what remains (iterative HNSW scan)
        narrow = await search.vector(embed(["falcon"])[0], build_filter(ctx(), SourceFilters(source_types=frozenset({"meeting"})), temporal="current"), 5)
        assert [h.ref_key for h in narrow] == ["meeting:m#3"]
        await pool.close()
        await index.close()

    asyncio.run(go())


def test_the_whole_pipeline_over_real_stores_never_exposes_what_the_caller_may_not_have(dsn, tmp_path):
    async def go():
        memory, planner, tasks = await PostgresMemoryStore.connect(dsn), await PostgresPlannerStore.connect(dsn), await PostgresTaskStore.connect(dsn)
        documents, meetings = await PostgresDocumentStore.connect(dsn, embed_fn=embed), await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        index, outbox = await PostgresKnowledgeIndex.connect(dsn), await PostgresOutbox.connect(dsn)
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        adapters = build_adapters(memory=memory, documents=documents, meetings=meetings, planner=planner, tasks=tasks)
        worker = IndexingWorker(adapters=adapters, index=index, outbox=outbox, embed_fn=embed, embedding_model="t")
        await memory.add_memory(content="Harbor default model is Falcon-7B", source="s", project_scope="harbor")
        await memory.add_memory(content="Tomas review is on Friday falcon", source="s", sensitivity=Privacy.SENSITIVE)
        await planner.add_note("Actions", "Tomas benchmarks Falcon-7B", project_scope="harbor")
        await planner.add_note("Lantern", "falcon rollback script", project_scope="lantern")
        await documents.ingest_document(title="Arch", content="# Model\nfalcon runs on the gpu host", source="s", project_scope="harbor")
        m = await meetings.create_meeting(title="Sync", audio=b"x", source_filename="a.wav", content_type="audio/wav", project_scope="harbor")
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("UPDATE meetings SET transcript_segments = %s, diarization_segments = %s, status = 'aligning' WHERE id = %s",
                         (Json([{"start": 0.0, "end": 1.0, "text": "we keep falcon as the default"}]),
                          Json([{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]), m.id))
        await worker.drain()
        assert await index.count() == 6
        for config in (B1A, B1B, B1A.__class__("B1a-nofilter", prefilter=False), B1A.__class__("B1b-nofilter", vector=True, prefilter=False)):
            retriever = Retriever(search=PostgresSearch(pool), adapters=adapters, config=config, embed_fn=embed)
            for caller in (ctx(), ctx(sensitivity_ceiling=Privacy.PUBLIC), ctx(project_scopes=frozenset({"lantern"})),
                           ctx(destinations=frozenset({"local", "cloud"})), access.access_for_owner("o", channel_private=False),
                           ctx(sensitivity_ceiling=Privacy.SENSITIVE)):
                result = await retriever.retrieve("falcon default model review rollback", caller)
                for item in result.bundle.items:
                    assert access.decide(caller, item) is None, (config.name, item.ref.key)
                if caller.sensitivity_ceiling != Privacy.SENSITIVE:
                    assert not any("review" in i.text for i in result.bundle.items)
        # stale: forget and cancel after indexing, without letting the worker run
        mem = (await memory.list_memories())[0]
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("ALTER TABLE memories DISABLE TRIGGER knowledge_memories")  # simulate a missed event
        await memory.forget(mem.id)
        stale_row = await index.get(f"memory:{mem.id}")
        assert stale_row is not None
        retriever = Retriever(search=PostgresSearch(pool), adapters=adapters, config=B1B, embed_fn=embed)
        for odd in ("falcon\x00model", "x" * 100000):
            assert (await retriever.retrieve(odd, ctx())).bundle is not None  # NUL and huge queries are cleaned, not passed to SQL as they are
        result = await retriever.retrieve("harbor default model falcon", ctx())
        assert f"memory:{mem.id}" not in [i.ref.key for i in result.bundle.items] and result.bundle.dropped.get("forgotten") == 1
        await pool.close()
        for part in (memory, planner, tasks, documents, meetings, index, outbox):
            await part.close()

    asyncio.run(go())
