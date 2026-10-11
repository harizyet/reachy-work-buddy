"""PostgreSQL store for the document library (migration 031). Every transition is one guarded statement, so a retry or a crash cannot resurrect a document that is being deleted."""

from __future__ import annotations

from datetime import datetime

from psycopg_pool import AsyncConnectionPool

from companion_core.document_library.models import Document, DocumentState, Priority
from shared.database import check_schema, close_pool, open_pool
from shared.models.response import Privacy

_COLUMNS = (
    "id, title, filename, mime_type, source_hash, size_bytes, sensitivity, project_scope, state, backend, backend_ref, backend_revision, tier, processing_priority, "
    "page_count, error_code, created_at, updated_at"
)
_KEYS = [k.strip() for k in _COLUMNS.split(",")]
_UPDATABLE = {"title", "project_scope", "sensitivity", "state", "backend_ref", "backend_revision", "tier", "processing_priority", "page_count", "error_code"}


def _document(row) -> Document:
    data = dict(zip(_KEYS, row, strict=True))
    data["sensitivity"], data["state"], data["processing_priority"] = Privacy(data["sensitivity"]), DocumentState(data["state"]), Priority(data["processing_priority"])
    return Document(**data)


def _value(value):
    return value.value if hasattr(value, "value") else value


class PostgresDocumentStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, source) -> PostgresDocumentStore:
        pool = await open_pool(source)
        async with pool.connection() as conn:
            await check_schema(conn)
        return cls(pool)

    async def close(self) -> None:
        await close_pool(self._pool)

    async def add(self, document: Document) -> Document:
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO documents ({_COLUMNS}) VALUES ({', '.join(['%s'] * len(_KEYS))})",
                tuple(_value(getattr(document, key)) for key in _KEYS),
            )
        return document

    async def get(self, document_id: str) -> Document | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_COLUMNS} FROM documents WHERE id = %s", (document_id,))).fetchone()
        return _document(row) if row else None

    async def list(self) -> list[Document]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_COLUMNS} FROM documents ORDER BY created_at DESC")).fetchall()
        return [_document(r) for r in rows]

    async def update(self, document_id: str, now: datetime, **fields) -> Document | None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"not an updatable field: {sorted(unknown)}")
        assignments = ", ".join(f"{name} = %s" for name in fields)
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                f"UPDATE documents SET {assignments}{', ' if assignments else ''}updated_at = %s WHERE id = %s AND state <> 'deleting' RETURNING {_COLUMNS}",
                (*[_value(v) for v in fields.values()], now, document_id))).fetchone()
        return _document(row) if row else None

    async def begin_delete(self, document_id: str, now: datetime) -> Document | None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE documents SET state = 'deleting', updated_at = %s WHERE id = %s AND state <> 'deleting'", (now, document_id))
            row = await (await conn.execute(f"SELECT {_COLUMNS} FROM documents WHERE id = %s", (document_id,))).fetchone()
        return _document(row) if row else None

    async def count_by_hash(self, source_hash: str) -> int:
        async with self._pool.connection() as conn:
            return (await (await conn.execute("SELECT count(*) FROM documents WHERE source_hash = %s", (source_hash,))).fetchone())[0]

    async def remove(self, document_id: str) -> bool:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            return cursor.rowcount > 0

    async def deleting(self) -> list[Document]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_COLUMNS} FROM documents WHERE state = 'deleting' ORDER BY updated_at")).fetchall()
        return [_document(r) for r in rows]
