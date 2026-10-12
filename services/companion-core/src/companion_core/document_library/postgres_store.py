"""PostgreSQL store for the document library (migration 031). Every transition is one guarded statement, so a retry or a crash cannot resurrect a document that is being deleted."""

from __future__ import annotations

from datetime import datetime

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from companion_core.document_library.models import (
    UPDATABLE_FIELDS,
    Document,
    DocumentOutput,
    DocumentState,
    OutputStatus,
    Priority,
)
from shared.database import check_schema, close_pool, open_pool
from shared.models.response import Privacy

_COLUMNS = (
    "id, title, filename, mime_type, source_hash, size_bytes, sensitivity, project_scope, state, backend, backend_ref, backend_revision, tier, processing_priority, "
    "page_count, error_code, created_at, updated_at"
)
_KEYS = [k.strip() for k in _COLUMNS.split(",")]


def _document(row) -> Document:
    data = dict(zip(_KEYS, row, strict=True))
    data["sensitivity"], data["state"], data["processing_priority"] = Privacy(data["sensitivity"]), DocumentState(data["state"]), Priority(data["processing_priority"])
    return Document(**data)


_OUT = (
    "id, document_id, kind, style, source_hash, tier, sensitivity, status, text, sections, pages_covered, page_count, truncated, model, prompt_version, stale, error_code, created_at, updated_at"
)
_OUT_KEYS = [k.strip() for k in _OUT.split(",")]
_OUT_UPDATABLE = {"status", "text", "sections", "pages_covered", "page_count", "truncated", "model", "error_code", "tier", "sensitivity"}


def _output(row) -> DocumentOutput:
    data = dict(zip(_OUT_KEYS, row, strict=True))
    data["sensitivity"], data["status"], data["sections"] = Privacy(data["sensitivity"]), OutputStatus(data["status"]), tuple(data["sections"] or ())
    return DocumentOutput(**data)


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
        unknown = set(fields) - UPDATABLE_FIELDS
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

    async def pending_sync(self) -> list[Document]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_COLUMNS} FROM documents WHERE state IN ('uploaded', 'queued', 'processing', 'partial') ORDER BY created_at")).fetchall()
        return [_document(r) for r in rows]

    # --- derived outputs ---------------------------------------------------------------------------------------

    async def begin_output(self, output: DocumentOutput) -> tuple[DocumentOutput, bool]:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"SELECT {_OUT} FROM document_outputs WHERE document_id = %s AND kind = %s AND style = %s AND NOT stale AND status IN ('running', 'ready')", (output.document_id, output.kind, output.style))).fetchone()
            if row:
                return _output(row), False
            cursor = await conn.execute(
                f"INSERT INTO document_outputs ({_OUT}) VALUES ({', '.join(['%s'] * len(_OUT_KEYS))}) ON CONFLICT DO NOTHING RETURNING id",
                tuple(Jsonb(list(output.sections)) if key == "sections" else _value(getattr(output, key)) for key in _OUT_KEYS))
            if await cursor.fetchone():
                return output, True
            row = await (await conn.execute(
                f"SELECT {_OUT} FROM document_outputs WHERE document_id = %s AND kind = %s AND style = %s AND NOT stale AND status IN ('running', 'ready')", (output.document_id, output.kind, output.style))).fetchone()
            return _output(row), False

    async def get_output(self, output_id: str) -> DocumentOutput | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_OUT} FROM document_outputs WHERE id = %s", (output_id,))).fetchone()
        return _output(row) if row else None

    async def list_outputs(self, document_id: str) -> list[DocumentOutput]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_OUT} FROM document_outputs WHERE document_id = %s ORDER BY created_at DESC", (document_id,))).fetchall()
        return [_output(r) for r in rows]

    async def finish_output(self, output_id: str, now: datetime, **fields) -> DocumentOutput | None:
        unknown = set(fields) - _OUT_UPDATABLE
        if unknown:
            raise ValueError(f"not an updatable field: {sorted(unknown)}")
        assignments = ", ".join(f"{name} = %s" for name in fields)
        values = [Jsonb(list(v)) if name == "sections" else _value(v) for name, v in fields.items()]
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"UPDATE document_outputs SET {assignments}{', ' if assignments else ''}updated_at = %s WHERE id = %s RETURNING {_OUT}", (*values, now, output_id))).fetchone()
        return _output(row) if row else None

    async def supersede_outputs(self, document_id: str, now: datetime, *, kind: str | None = None, style: str | None = None) -> int:
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "UPDATE document_outputs SET stale = TRUE, updated_at = %s WHERE document_id = %s AND NOT stale AND (%s::text IS NULL OR kind = %s) AND (%s::text IS NULL OR style = %s)",
                (now, document_id, kind, kind, style, style))
            return cursor.rowcount

    async def delete_outputs(self, document_id: str) -> int:
        async with self._pool.connection() as conn:
            return (await conn.execute("DELETE FROM document_outputs WHERE document_id = %s", (document_id,))).rowcount

    async def fail_running_outputs(self, now: datetime) -> int:
        async with self._pool.connection() as conn:
            return (await conn.execute("UPDATE document_outputs SET status = 'failed', error_code = 'interrupted', updated_at = %s WHERE status = 'running'", (now,))).rowcount
