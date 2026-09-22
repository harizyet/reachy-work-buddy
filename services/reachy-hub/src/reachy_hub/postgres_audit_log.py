"""Postgres-backed AuditLog. See audit_log.py for the interface."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from reachy_hub.audit_log import AuditEntry, _new_entry
from shared.models.interruption import InterruptionAction
from shared.models.response import Privacy
from shared.models.session import Channel, InteractionMode

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    mode TEXT NOT NULL,
    privacy TEXT NOT NULL,
    base_channel TEXT NOT NULL,
    delivery_channel TEXT NOT NULL,
    overridden BOOLEAN NOT NULL,
    action TEXT,
    created_at TIMESTAMPTZ NOT NULL
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS audit_log_user_id_created_at_idx
ON audit_log (user_id, created_at DESC)
"""

_COLUMNS = (
    "id, user_id, session_id, channel, mode, privacy, base_channel, "
    "delivery_channel, overridden, action, created_at"
)

_INSERT_SQL = f"INSERT INTO audit_log ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"


def _from_row(row: tuple) -> AuditEntry:
    return AuditEntry(
        id=row[0],
        user_id=row[1],
        session_id=row[2],
        channel=Channel(row[3]),
        mode=InteractionMode(row[4]),
        privacy=Privacy(row[5]),
        base_channel=Channel(row[6]),
        delivery_channel=Channel(row[7]),
        overridden=row[8],
        action=InterruptionAction(row[9]) if row[9] is not None else None,
        created_at=row[10],
    )


class PostgresAuditLog:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresAuditLog:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        log = cls(pool)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
            await conn.execute(_CREATE_INDEX_SQL)
        return log

    async def close(self) -> None:
        await self._pool.close()

    async def record(
        self,
        *,
        user_id: str,
        session_id: str,
        channel: Channel,
        mode: InteractionMode,
        privacy: Privacy,
        base_channel: Channel,
        delivery_channel: Channel,
        action: InterruptionAction | None = None,
    ) -> AuditEntry:
        entry = _new_entry(
            user_id=user_id,
            session_id=session_id,
            channel=channel,
            mode=mode,
            privacy=privacy,
            base_channel=base_channel,
            delivery_channel=delivery_channel,
            action=action,
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                _INSERT_SQL,
                (
                    entry.id,
                    entry.user_id,
                    entry.session_id,
                    entry.channel.value,
                    entry.mode.value,
                    entry.privacy.value,
                    entry.base_channel.value,
                    entry.delivery_channel.value,
                    entry.overridden,
                    entry.action.value if entry.action is not None else None,
                    entry.created_at,
                ),
            )
        return entry

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[AuditEntry]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM audit_log WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit),
            )
            rows = await cur.fetchall()
            return [_from_row(row) for row in rows]
