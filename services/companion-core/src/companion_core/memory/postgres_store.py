"""Postgres-backed MemoryStore. See store.py for the interface and the
expiry-at-read-time note."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from psycopg_pool import AsyncConnectionPool

from shared.models.memory import MemoryRecord, MemoryType
from shared.models.response import Privacy

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    project_scope TEXT,
    confidence DOUBLE PRECISION NOT NULL,
    sensitivity TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    last_accessed TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
)
"""

_COLUMNS = (
    "id, type, content, source, project_scope, confidence, "
    "sensitivity, created_at, last_accessed, expires_at"
)

_NOT_EXPIRED_SQL = "(expires_at IS NULL OR expires_at > %s)"


def _from_row(row: tuple) -> MemoryRecord:
    return MemoryRecord(
        id=row[0],
        type=MemoryType(row[1]),
        content=row[2],
        source=row[3],
        project_scope=row[4],
        confidence=row[5],
        sensitivity=Privacy(row[6]),
        created_at=row[7],
        last_accessed=row[8],
        expires_at=row[9],
    )


class PostgresMemoryStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresMemoryStore:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def add_memory(
        self,
        *,
        content: str,
        source: str,
        type: MemoryType = MemoryType.WORKING,
        project_scope: str | None = None,
        confidence: float = 1.0,
        sensitivity: Privacy = Privacy.WORK_PRIVATE,
        expires_at: datetime | None = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            type=type,
            content=content,
            source=source,
            project_scope=project_scope,
            confidence=confidence,
            sensitivity=sensitivity,
            expires_at=expires_at,
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO memories ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    record.id,
                    record.type.value,
                    record.content,
                    record.source,
                    record.project_scope,
                    record.confidence,
                    record.sensitivity.value,
                    record.created_at,
                    record.last_accessed,
                    record.expires_at,
                ),
            )
        return record

    async def recall(self, query: str, *, type: MemoryType | None = None) -> list[MemoryRecord]:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            if type is None:
                cur = await conn.execute(
                    f"SELECT {_COLUMNS} FROM memories "
                    f"WHERE {_NOT_EXPIRED_SQL} AND content ILIKE %s ORDER BY created_at",
                    (now, f"%{query}%"),
                )
            else:
                cur = await conn.execute(
                    f"SELECT {_COLUMNS} FROM memories "
                    f"WHERE {_NOT_EXPIRED_SQL} AND content ILIKE %s AND type = %s ORDER BY created_at",
                    (now, f"%{query}%", type.value),
                )
            rows = await cur.fetchall()
            records = [_from_row(row) for row in rows]

        if records:
            async with self._pool.connection() as conn:
                await conn.execute(
                    "UPDATE memories SET last_accessed = %s WHERE id = ANY(%s)",
                    (now, [r.id for r in records]),
                )
            for record in records:
                record.last_accessed = now
        return records

    async def list_memories(self, type: MemoryType | None = None) -> list[MemoryRecord]:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            if type is None:
                cur = await conn.execute(
                    f"SELECT {_COLUMNS} FROM memories WHERE {_NOT_EXPIRED_SQL} ORDER BY created_at", (now,)
                )
            else:
                cur = await conn.execute(
                    f"SELECT {_COLUMNS} FROM memories WHERE {_NOT_EXPIRED_SQL} AND type = %s ORDER BY created_at",
                    (now, type.value),
                )
            rows = await cur.fetchall()
            return [_from_row(row) for row in rows]

    async def get(self, memory_id: str) -> MemoryRecord | None:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM memories WHERE id = %s AND {_NOT_EXPIRED_SQL}", (memory_id, now)
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def forget(self, memory_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
            return cur.rowcount > 0
