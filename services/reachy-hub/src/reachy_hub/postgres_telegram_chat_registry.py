"""Postgres-backed TelegramChatRegistry. See telegram_chat_registry.py."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS telegram_chats (
    user_id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL
)
"""

_UPSERT_SQL = """
INSERT INTO telegram_chats (user_id, chat_id) VALUES (%s, %s)
ON CONFLICT (user_id) DO UPDATE SET chat_id = EXCLUDED.chat_id
"""


class PostgresTelegramChatRegistry:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresTelegramChatRegistry:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        registry = cls(pool)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        return registry

    async def close(self) -> None:
        await self._pool.close()

    async def get_chat_id(self, user_id: str) -> int | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT chat_id FROM telegram_chats WHERE user_id = %s", (user_id,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_chat_id(self, user_id: str, chat_id: int) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(_UPSERT_SQL, (user_id, chat_id))
