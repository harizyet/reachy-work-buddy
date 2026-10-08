"""Tracks which completed/failed/lost coding-agent sessions have already
been surfaced to the owner, so reachy-hub's polling of
`GET /coding-agents/completions/due` doesn't re-notify for the same
session on every poll — same "claim it once" shape as
accounts/store.py's `claim_reminders`.

The claims are durable (migration 013). Coding-agent sessions themselves now
survive restarts, so an in-memory ledger would re-notify the owner of every
historical finished session each time core restarts. The ledger lives in
this service's own table with no foreign key to the session rows: those are
owned by coding-agent-service, which core reaches only over HTTP.
"""

from __future__ import annotations

from typing import Protocol

from psycopg_pool import AsyncConnectionPool

from shared.database import check_schema, connection_pool


class CodingAgentNotificationStore(Protocol):
    async def claim(self, session_id: str) -> bool:
        """True the first time this session_id is claimed, False on every
        later call — the caller notifies only when this returns True."""
        ...


class InMemoryCodingAgentNotificationStore:
    def __init__(self) -> None:
        self._claimed: set[str] = set()

    async def claim(self, session_id: str) -> bool:
        if session_id in self._claimed:
            return False
        self._claimed.add(session_id)
        return True


class PostgresCodingAgentNotificationStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresCodingAgentNotificationStore:
        pool = connection_pool(dsn)
        await pool.open()
        try:
            async with pool.connection() as conn:
                await check_schema(conn)
            return cls(pool)
        except BaseException:
            await pool.close()
            raise

    async def close(self) -> None:
        await self._pool.close()

    async def claim(self, session_id: str) -> bool:
        # The insert itself is the atomic claim: concurrent pollers cannot
        # both see a row inserted.
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO coding_agent_notifications (session_id, claimed_at) VALUES (%s, now()) "
                "ON CONFLICT DO NOTHING",
                (session_id,),
            )
            return cur.rowcount == 1
