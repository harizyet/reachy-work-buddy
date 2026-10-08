"""The derived knowledge index (Phase 44B): one searchable row per retrievable part of a source, holding match text, an embedding and
the metadata a filter needs. It is rebuildable from the stores and is never the source of truth: a row can be stale, and retrieval
re-reads the source before anything is returned (revalidate.py). Search over it arrives in 44D; this module only stores and compares.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import psycopg
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from companion_core.knowledge.sources import Indexable
from shared.database import check_schema
from shared.models.response import Privacy


@dataclass(frozen=True)
class IndexRow:
    ref_key: str
    source_type: str
    source_id: str
    locator: str | None
    kind: str
    source_version: str
    match_text: str
    sensitivity: Privacy
    project_scope: str | None
    local_only: bool
    confidence: float
    observed_at: datetime | None
    valid_from: datetime | None
    valid_until: datetime | None
    embedding_model: str
    indexed_at: datetime

    @classmethod
    def from_indexable(cls, item: Indexable, *, embedding_model: str, now: datetime) -> IndexRow:
        return cls(
            ref_key=item.ref.key, source_type=item.ref.source_type, source_id=item.ref.source_id, locator=item.ref.locator,
            kind=item.kind, source_version=item.version(), match_text=item.match_text, sensitivity=item.sensitivity,
            project_scope=item.project_scope, local_only=item.local_only, confidence=item.confidence,
            observed_at=item.observed_at, valid_from=item.valid_from, valid_until=item.valid_until,
            embedding_model=embedding_model, indexed_at=now,
        )


class KnowledgeIndex(Protocol):
    async def rows_for_source(self, source_type: str, source_id: str) -> dict[str, IndexRow]: ...
    async def upsert(self, rows: list[IndexRow], embeddings: list[list[float]]) -> None: ...
    async def delete_keys(self, keys: list[str]) -> None: ...
    async def delete_source(self, source_type: str, source_id: str) -> int: ...
    async def source_ids(self) -> set[tuple[str, str]]: ...
    async def get(self, ref_key: str) -> IndexRow | None: ...
    async def count(self) -> int: ...


class InMemoryKnowledgeIndex:
    def __init__(self) -> None:
        self.rows: dict[str, IndexRow] = {}
        self.embeddings: dict[str, list[float]] = {}

    async def rows_for_source(self, source_type: str, source_id: str) -> dict[str, IndexRow]:
        return {k: r for k, r in self.rows.items() if (r.source_type, r.source_id) == (source_type, source_id)}

    async def upsert(self, rows: list[IndexRow], embeddings: list[list[float]]) -> None:
        for row, vector in zip(rows, embeddings, strict=True):
            self.rows[row.ref_key] = row
            self.embeddings[row.ref_key] = vector

    async def delete_keys(self, keys: list[str]) -> None:
        for key in keys:
            self.rows.pop(key, None)
            self.embeddings.pop(key, None)

    async def delete_source(self, source_type: str, source_id: str) -> int:
        keys = list(await self.rows_for_source(source_type, source_id))
        await self.delete_keys(keys)
        return len(keys)

    async def source_ids(self) -> set[tuple[str, str]]:
        return {(r.source_type, r.source_id) for r in self.rows.values()}

    async def get(self, ref_key: str) -> IndexRow | None:
        return self.rows.get(ref_key)

    async def count(self) -> int:
        return len(self.rows)


_COLUMNS = (
    "ref_key, source_type, source_id, locator, kind, source_version, match_text, sensitivity, project_scope, local_only, "
    "confidence, observed_at, valid_from, valid_until, embedding_model, indexed_at"
)


def _row(r: tuple) -> IndexRow:
    return IndexRow(
        ref_key=r[0], source_type=r[1], source_id=r[2], locator=r[3], kind=r[4], source_version=r[5], match_text=r[6],
        sensitivity=Privacy(r[7]), project_scope=r[8], local_only=r[9], confidence=r[10], observed_at=r[11], valid_from=r[12],
        valid_until=r[13], embedding_model=r[14], indexed_at=r[15],
    )


class PostgresKnowledgeIndex:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresKnowledgeIndex:
        # Same ordering as PostgresDocumentStore: check the revision before registering the vector type.
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=10) as conn:
            await check_schema(conn)
        # Small on purpose: the stack shares one PostgreSQL (max_connections 100) and every other store already holds a pool of 4. The
        # 2026-10-08 trial hit "too many clients" with default pools; the indexer is background work and needs one or two.
        pool = AsyncConnectionPool(dsn, open=False, min_size=1, max_size=2, configure=register_vector_async)
        await pool.open()
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def rows_for_source(self, source_type: str, source_id: str) -> dict[str, IndexRow]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM knowledge_items WHERE source_type = %s AND source_id = %s", (source_type, source_id)
            )
            return {r[0]: _row(r) for r in await cur.fetchall()}

    async def upsert(self, rows: list[IndexRow], embeddings: list[list[float]]) -> None:
        if not rows:
            return
        async with self._pool.connection() as conn, conn.transaction():
            for row, vector in zip(rows, embeddings, strict=True):
                await conn.execute(
                    f"INSERT INTO knowledge_items ({_COLUMNS}, embedding) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector) "
                    "ON CONFLICT (ref_key) DO UPDATE SET source_version = EXCLUDED.source_version, match_text = EXCLUDED.match_text, "
                    "kind = EXCLUDED.kind, sensitivity = EXCLUDED.sensitivity, project_scope = EXCLUDED.project_scope, "
                    "local_only = EXCLUDED.local_only, confidence = EXCLUDED.confidence, observed_at = EXCLUDED.observed_at, "
                    "valid_from = EXCLUDED.valid_from, valid_until = EXCLUDED.valid_until, "
                    "embedding_model = EXCLUDED.embedding_model, indexed_at = EXCLUDED.indexed_at, embedding = EXCLUDED.embedding",
                    (
                        row.ref_key, row.source_type, row.source_id, row.locator, row.kind, row.source_version, row.match_text,
                        row.sensitivity.value, row.project_scope, row.local_only, row.confidence, row.observed_at, row.valid_from,
                        row.valid_until, row.embedding_model, row.indexed_at, vector,
                    ),
                )

    async def delete_keys(self, keys: list[str]) -> None:
        if keys:
            async with self._pool.connection() as conn:
                await conn.execute("DELETE FROM knowledge_items WHERE ref_key = ANY(%s)", (keys,))

    async def delete_source(self, source_type: str, source_id: str) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM knowledge_items WHERE source_type = %s AND source_id = %s", (source_type, source_id)
            )
            return cur.rowcount

    async def source_ids(self) -> set[tuple[str, str]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT DISTINCT source_type, source_id FROM knowledge_items")
            return {(r[0], r[1]) for r in await cur.fetchall()}

    async def get(self, ref_key: str) -> IndexRow | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM knowledge_items WHERE ref_key = %s", (ref_key,))
            row = await cur.fetchone()
            return _row(row) if row else None

    async def count(self) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT count(*) FROM knowledge_items")
            return (await cur.fetchone())[0]


def utcnow() -> datetime:
    return datetime.now(UTC)
