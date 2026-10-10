"""Phase 44E integration on real PostgreSQL (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector): the selective answerer over the real stores, the real index and worker, the real
SQL search and retrieval-time revalidation. Covers a correct cited answer, restricted and stale records, a conflict, absence versus a dead dependency, and that no model is ever involved."""

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from companion_core.knowledge import selective_answer as sa
from companion_core.knowledge.index import PostgresKnowledgeIndex
from companion_core.knowledge.outbox import PostgresOutbox
from companion_core.knowledge.qualify import build_vocabulary
from companion_core.knowledge.retrieval import B1A, Retriever
from companion_core.knowledge.search import PostgresSearch
from companion_core.knowledge.sources import build_adapters
from companion_core.knowledge.worker import IndexingWorker
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.migrations.__main__ import upgrade
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.secrets import Keyring
from companion_core.tasks.postgres_store import PostgresTaskStore
from psycopg_pool import AsyncConnectionPool

from shared.models.response import Privacy

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector"
)


def hashing_embed(texts):
    out = []
    for text in texts:
        vector = [0.0] * 384
        for word in text.lower().split():
            vector[int(hashlib.md5(word.strip(".,:").encode()).hexdigest(), 16) % 384] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        out.append([v / norm for v in vector] if norm else vector)
    return out


KEYS = Keyring("one", {"one": b"\x01" * 32})
OWNER_Q = "Who owns the Ferry queue?"


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


async def build(dsn, tmp_path):
    memory, planner, tasks = await PostgresMemoryStore.connect(dsn), await PostgresPlannerStore.connect(dsn), await PostgresTaskStore.connect(dsn)
    documents, meetings = await PostgresDocumentStore.connect(dsn, embed_fn=hashing_embed), await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
    index, outbox = await PostgresKnowledgeIndex.connect(dsn), await PostgresOutbox.connect(dsn)
    pool = AsyncConnectionPool(dsn, open=False)
    await pool.open()
    adapters = build_adapters(memory=memory, documents=documents, meetings=meetings, planner=planner, tasks=tasks)
    worker = IndexingWorker(adapters=adapters, index=index, outbox=outbox, embed_fn=hashing_embed, embedding_model="t")
    answerer = sa.SelectiveAnswerer(
        retriever=Retriever(search=PostgresSearch(pool), adapters=adapters, config=B1A, clock=lambda: datetime.now(UTC)),
        index_count=PostgresKnowledgeIndex(pool).count, vocabulary=lambda: build_vocabulary(adapters))
    parts = (memory, planner, tasks, documents, meetings, index, outbox)
    return memory, documents, worker, answerer, pool, parts


async def close(pool, parts):
    await pool.close()
    for part in parts:
        await part.close()


def test_correct_cited_answers_over_real_postgres_with_restricted_stale_and_conflicting_records(dsn, tmp_path):
    async def go():
        memory, documents, worker, answerer, pool, parts = await build(dsn, tmp_path)
        dana = await memory.add_memory(content="The owner of the Ferry queue is Dana Whitfield.", source="conversation", sensitivity=Privacy.WORK_PRIVATE)
        await memory.add_memory(content="The owner of the Zephyr cache is Marcus Ode.", source="conversation", sensitivity=Privacy.SENSITIVE)
        await memory.add_memory(content="The owner of the Quill scheduler is Priya Raman.", source="conversation", sensitivity=Privacy.PUBLIC)
        await documents.ingest_document(title="Harbor architecture", content="# Limits\nThe retry limit of Harbor is 5 retries.", source="s")
        await worker.drain()
        await answerer.start()

        out = await answerer.answer(OWNER_Q, modality="text")
        assert out.handler == sa.HANDLER_ANSWER and out.reply.startswith("The owner of the Ferry queue is Dana Whitfield [E1].") and out.privacy == Privacy.WORK_PRIVATE
        assert out.cited == (f"memory:{dana.id}",)
        retry = await answerer.answer("How many retries before a failed Harbor job is parked?", modality="text")
        assert "5 retries [E1]" in retry.reply and "Harbor architecture (document)" in retry.reply
        spoken = await answerer.answer("Who owns the Quill scheduler?", modality="voice")
        assert spoken.reply == "The owner of the Quill scheduler is Priya Raman." and spoken.privacy == Privacy.PUBLIC

        # a sensitive record is never read, named or counted: the question about it is not even a knowledge question the owner's records can anchor
        restricted = await answerer.answer("Who owns the Zephyr cache?", modality="text")
        assert restricted is None or "Marcus" not in restricted.reply

        # a record that conflicts is shown as a conflict, never resolved
        await memory.add_memory(content="The owner of the Ferry queue is Marcus Ode.", source="conversation", sensitivity=Privacy.WORK_PRIVATE)
        await worker.drain()
        conflict = await answerer.answer(OWNER_Q, modality="text")
        assert conflict.reply.startswith("The records disagree on the owner of the Ferry queue:") and "They do not say which applies." in conflict.reply

        # a stale index row (a forgotten record the worker has not yet removed) is dropped at retrieval time
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("ALTER TABLE memories DISABLE TRIGGER knowledge_memories")
        await memory.forget(dana.id)
        after = await answerer.answer(OWNER_Q, modality="text")
        assert "Dana Whitfield" not in after.reply and after.handler == sa.HANDLER_ANSWER

        # absence of evidence is an answer; a dead dependency is a failure
        none = await answerer.answer("What is the default model for Quill?", modality="text")
        assert none.handler == sa.HANDLER_ANSWER and none.reply == sa.ZERO_EVIDENCE_REPLY
        await pool.close()
        dead = await answerer.answer(OWNER_Q, modality="text")
        assert dead.handler == sa.HANDLER_FAILURE and dead.reply == sa.FAILURE_REPLY
        counts = answerer.stats.counts
        assert counts["failed_not_ready"] + counts["failed_retrieval"] + counts["failed_error"] == 1
        for part in parts:
            await part.close()

    asyncio.run(go())


def test_an_empty_index_is_a_dependency_failure_not_an_absence_answer(dsn, tmp_path):
    async def go():
        memory, _documents, _worker, answerer, pool, parts = await build(dsn, tmp_path)
        await memory.add_memory(content="The owner of the Ferry queue is Dana Whitfield.", source="conversation")  # never indexed: the worker has not run
        await answerer.start()
        answerer._terms = frozenset({"quill"})
        out = await answerer.answer("Who owns the Quill message queue?", modality="text")
        assert out.handler == sa.HANDLER_FAILURE and answerer.stats.counts["failed_not_ready"] == 1
        await close(pool, parts)

    asyncio.run(go())
