"""Postgres-backed SessionStore. See session_store.py for the interface."""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg_pool import AsyncConnectionPool

from reachy_hub.session_store import _new_session
from shared.database import check_schema
from shared.models.session import AgentSession, Channel, InteractionMode, PrivacyContext

_COLUMNS = (
    "session_id, user_id, conversation_id, active_channel, "
    "interaction_mode, privacy_context, created_at, last_active_at, "
    "dnd, last_interruption_at"
)

_INSERT_SQL = f"""
INSERT INTO sessions ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        dnd=row[8],
        last_interruption_at=row[9],
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
            await check_schema(conn)
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
                    session.dnd,
                    session.last_interruption_at,
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

    async def set_mode(self, session: AgentSession, mode: InteractionMode) -> AgentSession:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE sessions SET interaction_mode = %s, last_active_at = %s WHERE session_id = %s",
                (mode.value, now, session.session_id),
            )
        session.interaction_mode = mode
        session.last_active_at = now
        return session

    async def set_dnd(self, session: AgentSession, dnd: bool) -> AgentSession:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE sessions SET dnd = %s, last_active_at = %s WHERE session_id = %s",
                (dnd, now, session.session_id),
            )
        session.dnd = dnd
        session.last_active_at = now
        return session

    async def set_privacy_context(self, session: AgentSession, privacy_context: PrivacyContext) -> AgentSession:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE sessions SET privacy_context = %s, last_active_at = %s WHERE session_id = %s",
                (privacy_context.value, now, session.session_id),
            )
        session.privacy_context = privacy_context
        session.last_active_at = now
        return session

    async def record_interruption(self, session: AgentSession, at: datetime) -> AgentSession:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE sessions SET last_interruption_at = %s WHERE session_id = %s",
                (at, session.session_id),
            )
        session.last_interruption_at = at
        return session
