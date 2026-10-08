"""The corpus built into real Postgres (the real stores, the 027 index, the real indexing worker), for benchmarking the retrieval
configurations that need PostgreSQL full-text search and pgvector. A fresh database is created for each run and dropped afterwards;
the server comes from KBENCH_DATABASE_URL (or DATABASE_MIGRATION_TEST_URL) and must be disposable."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from companion_core.knowledge.index import PostgresKnowledgeIndex
from companion_core.knowledge.outbox import PostgresOutbox
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
from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

from shared.models.memory import MemoryType
from shared.models.response import Privacy

DIM = 384


def hashing_embed_384(texts: list[str]) -> list[list[float]]:
    """The deterministic stand-in embedder at the index's width (md5 buckets of words); lexical in spirit, reproducible, no download."""
    out = []
    for text in texts:
        vector = [0.0] * DIM
        for word in "".join(ch if ch.isalnum() else " " for ch in text.lower()).split():
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        out.append([v / norm for v in vector] if norm else vector)
    return out


def admin_url() -> str:
    url = os.environ.get("KBENCH_DATABASE_URL") or os.environ.get("DATABASE_MIGRATION_TEST_URL")
    if not url:
        raise RuntimeError("set KBENCH_DATABASE_URL (a disposable Postgres with pgvector) to benchmark the PostgreSQL configurations")
    return url


@dataclass
class PgCorpus:
    dsn: str
    admin: str
    name: str
    pool: AsyncConnectionPool
    search: PostgresSearch
    adapters: dict
    worker: IndexingWorker
    stores: list
    tmp: tempfile.TemporaryDirectory
    store_id: dict[str, str] = field(default_factory=dict)  # "type:logical id" -> real id
    logical: dict[tuple[str, str], str] = field(default_factory=dict)  # (type, real id) -> logical id
    build_seconds: float = 0.0
    index_rows: int = 0

    def logical_key(self, ref_key: str) -> str:
        source_type, _, rest = ref_key.partition(":")
        real, _, locator = rest.partition("#")
        logical = self.logical.get((source_type, real), real)
        return f"{source_type}:{logical}" + (f"#{locator}" if locator else "")

    async def fingerprint(self) -> str:
        """A hash of every authoritative table (not the derived index, not read stamps), to prove retrieval changed nothing."""
        tables = ("memories", "document_chunks", "meetings", "notes", "tasks", "reminders")
        parts = []
        async with self.pool.connection() as conn:
            for table in tables:
                cur = await conn.execute(
                    f"SELECT coalesce(md5(string_agg((to_jsonb(t) - ARRAY['last_accessed','updated_at','embedding'])::text, '|' ORDER BY t.id)), '') FROM {table} t"
                )
                parts.append((await cur.fetchone())[0])
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    async def close(self) -> None:
        await self.pool.close()
        for store in self.stores:
            await store.close()
        self.tmp.cleanup()
        with psycopg.connect(self.admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')


async def build_pg_corpus(spec: dict[str, Any], embed_fn, embedding_model: str) -> PgCorpus:
    admin = admin_url()
    name = "kbench_" + uuid4().hex[:12]
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(admin, dbname=name)
    upgrade(dsn, Keyring("bench", {"bench": b"\x07" * 32}))
    tmp = tempfile.TemporaryDirectory()
    memory, planner, tasks = await PostgresMemoryStore.connect(dsn), await PostgresPlannerStore.connect(dsn), await PostgresTaskStore.connect(dsn)
    documents = await PostgresDocumentStore.connect(dsn, embed_fn=embed_fn)
    meetings = await PostgresMeetingStore.connect(dsn, audio_dir=Path(tmp.name))
    index, outbox = await PostgresKnowledgeIndex.connect(dsn), await PostgresOutbox.connect(dsn)
    pool = AsyncConnectionPool(dsn, open=False)
    await pool.open()
    adapters = build_adapters(memory=memory, documents=documents, meetings=meetings, planner=planner, tasks=tasks)
    worker = IndexingWorker(adapters=adapters, index=index, outbox=outbox, embed_fn=embed_fn, embedding_model=embedding_model)
    env = PgCorpus(dsn, admin, name, pool, PostgresSearch(pool), adapters, worker, [memory, planner, tasks, documents, meetings, index, outbox], tmp)

    def link(kind: str, logical_id: str, real_id: str) -> None:
        env.store_id[f"{kind}:{logical_id}"] = real_id
        env.logical[(kind, real_id)] = logical_id

    with psycopg.connect(dsn, autocommit=True) as conn:
        for item in spec["memories"]:
            record = await memory.add_memory(
                content=item["text"], source="benchmark", type=MemoryType(item["type"]), project_scope=item["scope"],
                sensitivity=Privacy(item["sensitivity"]),
                expires_at=datetime.fromisoformat(item["expires"]) if item.get("expires") else None,
            )
            conn.execute("UPDATE memories SET created_at = %s WHERE id = %s", (datetime.fromisoformat(item["created"]), record.id))
            link("memory", item["id"], record.id)
            if item.get("forgotten"):
                await memory.forget(record.id)
        for doc in spec["documents"]:
            chunks = await documents.ingest_document(title=doc["title"], content=doc["content"], source=doc["source"],
                                                     sensitivity=Privacy(doc["sensitivity"]), project_scope=doc["scope"])
            link("document", doc["id"], chunks[0].document_id)
        for entry in spec["meetings"]:
            m = await meetings.create_meeting(title=entry["title"], audio=b"x", source_filename="m.wav", content_type="audio/wav",
                                              project_scope=entry["scope"], sensitivity=Privacy(entry["sensitivity"]))
            segments = [{k: v for k, v in s.items() if k != "speaker"} for s in entry["segments"]]
            diar = [{"start": s["start"], "end": s["end"], "speaker": s["speaker"]} for s in entry["segments"]]
            conn.execute("UPDATE meetings SET transcript_segments = %s, diarization_segments = %s, status = 'aligning' WHERE id = %s",
                         (Json(segments), Json(diar), m.id))
            await meetings.set_speaker_names(m.id, entry["speaker_names"])
            for index_, text in entry["corrections"].items():
                await meetings.set_correction(m.id, int(index_), text)
            link("meeting", entry["id"], m.id)
        for note in spec["notes"]:
            record = await planner.add_note(note["title"], note["body"], sensitivity=Privacy(note["sensitivity"]), project_scope=note["scope"])
            link("note", note["id"], record.id)
        for task in spec["tasks"]:
            record = await tasks.add_task(task["text"], sensitivity=Privacy(task["sensitivity"]), project_scope=task["scope"])
            if task["done"]:
                await tasks.complete_task(record.id)
            link("task", task["id"], record.id)
        for reminder in spec["reminders"]:
            record = await planner.add_reminder(reminder["text"], datetime.fromisoformat("2030-01-01T10:00:00+00:00"),
                                                sensitivity=Privacy(reminder["sensitivity"]))
            link("reminder", reminder["id"], record.id)
    started = time.perf_counter()
    await worker.drain(max_rounds=10000)
    env.build_seconds = time.perf_counter() - started
    env.index_rows = await index.count()
    return env
