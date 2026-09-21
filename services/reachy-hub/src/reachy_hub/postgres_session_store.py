"""Postgres-backed SessionStore. See session_store.py for the interface."""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg_pool import AsyncConnectionPool

from reachy_hub.session_store import _new_session
from shared.models.session import AgentSession, Channel, InteractionMode, PrivacyContext

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    conversation_id TEXT NOT NULL,
    active_channel TEXT NOT NULL,
    interaction_mode TEXT NOT NULL,
    privacy_context TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    last_active_at TIMESTAMPTZ NOT NULL
)
"""

_COLUMNS = (
    "session_id, user_id, conversation_id, active_channel, "
    "interaction_mode, privacy_context, created_at, last_active_at"
)

_INSERT_SQL = f"""
INSERT INTO sessions ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (user_id) DO NOTHING
"""


def _from_row(row: tuple) -> AgentSession:
    return AgentSession(
        session_id=row[0],
        user_id=row[1],
        conversation_id=row[2],
        active_channel=Channel(row[3]),
        interaction_mode=InteractionMode(row[4]),
        privacy_context=PrivacyContext(row[5]),
        created_at=row[6],
        last_active_at=row[7],
    )


class PostgresSessionStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresSessionStore:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def get_by_user(self, user_id: str) -> AgentSession | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM sessions WHERE user_id = %s", (user_id,))
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def get_or_create(self, user_id: str, channel: Channel) -> AgentSession:
        existing = await self.get_by_user(user_id)
        if existing is not None:
            return existing

        session = _new_session(user_id, channel)
        async with self._pool.connection() as conn:
            await conn.execute(
                _INSERT_SQL,
                (
                    session.session_id,
                    session.user_id,
                    session.conversation_id,
                    session.active_channel.value,
                    session.interaction_mode.value,
                    session.privacy_context.value,
                    session.created_at,
                    session.last_active_at,
                ),
            )
        # ON CONFLICT DO NOTHING means a concurrent get_or_create for the
        # same user may have won the race; re-read to return the one row
        # that actually exists rather than the (possibly discarded) local
        # session object.
        return await self.get_by_user(user_id) or session

    async def touch_channel(self, session: AgentSession, channel: Channel) -> AgentSession:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE sessions SET active_channel = %s, last_active_at = %s WHERE session_id = %s",
                (channel.value, now, session.session_id),
            )
        session.active_channel = channel
        session.last_active_at = now
        return session
