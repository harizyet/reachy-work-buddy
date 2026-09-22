"""Postgres-backed DocumentStore, using the pgvector extension for
similarity search (`ORDER BY embedding <=> query_vector`, cosine distance
— docs/plan.md §8 calls out pgvector as the starting vector store). See
store.py for the interface, embeddings.py for the default embedder, and
the embed_fn injection note there for why tests don't hit this via the
real model.
"""

from __future__ import annotations

import uuid

import psycopg
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from companion_core.rag.chunking import split_into_chunks
from companion_core.rag.embeddings import EMBEDDING_DIM, embed
from companion_core.rag.store import EmbedFn
from shared.models.rag import DocumentChunk, RetrievedChunk

_CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector"
_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    document_title TEXT NOT NULL,
    section TEXT,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    embedding VECTOR({EMBEDDING_DIM}) NOT NULL
)
"""

_COLUMNS = "id, document_id, document_title, section, content, source, chunk_index, created_at"


def _from_row(row: tuple) -> DocumentChunk:
    return DocumentChunk(
        id=row[0],
        document_id=row[1],
        document_title=row[2],
        section=row[3],
        content=row[4],
        source=row[5],
        chunk_index=row[6],
        created_at=row[7],
    )


class PostgresDocumentStore:
    def __init__(self, pool: AsyncConnectionPool, *, embed_fn: EmbedFn = embed) -> None:
        self._pool = pool
        self._embed_fn = embed_fn

    @classmethod
    async def connect(cls, dsn: str, *, embed_fn: EmbedFn = embed) -> PostgresDocumentStore:
        # CREATE EXTENSION once, on its own connection, before the pool
        # opens — doing it inside the pool's per-connection `configure`
        # callback (as first tried) raced under real concurrent connection
        # startup: multiple connections ran "IF NOT EXISTS" at once and hit
        # Postgres's pg_extension_name_index unique constraint anyway.
        # Confirmed by a real `docker compose up`, not caught by unit tests
        # since they never exercise this Postgres path.
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
            await conn.execute(_CREATE_EXTENSION_SQL)

        pool = AsyncConnectionPool(dsn, open=False, configure=register_vector_async)
        await pool.open()
        store = cls(pool, embed_fn=embed_fn)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def ingest_document(self, *, title: str, content: str, source: str) -> list[DocumentChunk]:
        document_id = str(uuid.uuid4())
        pieces = split_into_chunks(content)
        vectors = self._embed_fn([text for _, text in pieces])
        chunks: list[DocumentChunk] = []
        async with self._pool.connection() as conn:
            for index, ((section, text), vector) in enumerate(zip(pieces, vectors, strict=True)):
                chunk = DocumentChunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    document_title=title,
                    section=section,
                    content=text,
                    source=source,
                    chunk_index=index,
                )
                await conn.execute(
                    f"INSERT INTO document_chunks ({_COLUMNS}, embedding) "
                    f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.document_title,
                        chunk.section,
                        chunk.content,
                        chunk.source,
                        chunk.chunk_index,
                        chunk.created_at,
                        vector,
                    ),
                )
                chunks.append(chunk)
        return chunks

    async def search(self, query: str, *, top_k: int = 3) -> list[RetrievedChunk]:
        (query_vector,) = self._embed_fn([query])
        async with self._pool.connection() as conn:
            # Explicit ::vector cast: a bare %s here is sent as a
            # double-precision array (psycopg's default numeric-list
            # adapter), and Postgres has no `vector <=> double precision[]`
            # operator — confirmed by a real docker compose run against
            # real pgvector, not caught by unit tests since they never hit
            # this Postgres path.
            cur = await conn.execute(
                f"SELECT {_COLUMNS}, 1 - (embedding <=> %s::vector) AS score FROM document_chunks "
                f"ORDER BY embedding <=> %s::vector LIMIT %s",
                (query_vector, query_vector, top_k),
            )
            rows = await cur.fetchall()
        return [RetrievedChunk(chunk=_from_row(row[:8]), score=row[8]) for row in rows]

    async def list_documents(self) -> list[str]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT DISTINCT document_title FROM document_chunks ORDER BY document_title")
            rows = await cur.fetchall()
        return [row[0] for row in rows]
