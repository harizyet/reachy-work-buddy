"""Postgres-backed ConfirmationStore. See store.py for the interface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from psycopg_pool import AsyncConnectionPool

from companion_core.consent.models import (
    ActionScope,
    ConfirmationRequest,
    ConfirmationStatus,
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS confirmation_requests (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    description TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    confirmed_at TIMESTAMPTZ
)
"""

_COLUMNS = "id, action_type, target_id, description, scope, status, created_at, expires_at, confirmed_at"


def _from_row(row: tuple) -> ConfirmationRequest:
    return ConfirmationRequest(
        id=row[0],
        action_type=row[1],
        target_id=row[2],
        description=row[3],
        scope=ActionScope(row[4]),
        status=ConfirmationStatus(row[5]),
        created_at=row[6],
        expires_at=row[7],
        confirmed_at=row[8],
    )


class PostgresConfirmationStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresConfirmationStore:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def create(
        self, *, action_type: str, target_id: str, description: str, scope: ActionScope, ttl_seconds: int
    ) -> ConfirmationRequest:
        now = datetime.now(UTC)
        request = ConfirmationRequest(
            action_type=action_type,
            target_id=target_id,
            description=description,
            scope=scope,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO confirmation_requests ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    request.id,
                    request.action_type,
                    request.target_id,
                    request.description,
                    request.scope.value,
                    request.status.value,
                    request.created_at,
                    request.expires_at,
                    request.confirmed_at,
                ),
            )
        return request

    async def get(self, confirmation_id: str) -> ConfirmationRequest | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM confirmation_requests WHERE id = %s", (confirmation_id,)
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def find_pending(self, action_type: str, query: str) -> ConfirmationRequest | None:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM confirmation_requests "
                f"WHERE action_type = %s AND status = %s AND expires_at > %s AND description ILIKE %s "
                f"ORDER BY created_at LIMIT 1",
                (action_type, ConfirmationStatus.PENDING.value, now, f"%{query}%"),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def confirm(self, confirmation_id: str) -> ConfirmationRequest | None:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE confirmation_requests SET status = %s, confirmed_at = %s "
                f"WHERE id = %s AND status = %s AND expires_at > %s RETURNING {_COLUMNS}",
                (ConfirmationStatus.CONFIRMED.value, now, confirmation_id, ConfirmationStatus.PENDING.value, now),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None
