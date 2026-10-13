"""PostgreSQL storage for the calendar feed (migration 033). One row, `calendar_feed`, for the single owner.

The feed URL is a bearer secret, so the row holds only a reference to the encrypted `secrets` table (companion_core/secrets.py), the same store the Google account uses. The URL
is read back only to download the feed and never leaves this process. The snapshot holds `EventFacts` (no description); the status holds fixed error codes.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from companion_core.calendar.feed import FeedConfig, FeedState, FeedStatus, Snapshot
from companion_core.secrets import PostgresSecretStore, SecretContext, SecretUnavailable
from shared.database import check_schema, close_pool, open_pool

CONTEXT = SecretContext(owner="owner", provider="ics", purpose="feed-url")


class PostgresFeedStore:
    def __init__(self, pool, secrets: PostgresSecretStore) -> None:
        self._pool, self._secrets = pool, secrets

    @classmethod
    async def connect(cls, source, secrets: PostgresSecretStore) -> PostgresFeedStore:
        pool = await open_pool(source)
        store = cls(pool, secrets)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await close_pool(self._pool)

    async def load(self) -> FeedState:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("SELECT secret_ref, config, overrides, snapshot, status FROM calendar_feed WHERE id = 'owner'")
            row = await cursor.fetchone()
        if row is None:
            return FeedState()
        ref, config, overrides, snapshot, status = row
        return FeedState(
            configured=ref is not None, config=FeedConfig.model_validate(config or {}), overrides=overrides or {},
            snapshot=Snapshot.model_validate(snapshot) if snapshot else None, status=FeedStatus.model_validate(status or {}),
        )

    async def get_url(self) -> str | None:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("SELECT secret_ref FROM calendar_feed WHERE id = 'owner' FOR UPDATE")
            row = await cursor.fetchone()
            if row is None or row[0] is None:
                return None
            try:
                return await self._secrets.resolve(conn, CONTEXT, row[0])
            except SecretUnavailable:
                return None  # the key or the secret is gone; the owner sets the URL again

    async def set_url(self, url: str, host: str) -> None:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("SELECT secret_ref FROM calendar_feed WHERE id = 'owner' FOR UPDATE")
            row = await cursor.fetchone()
            existing = row[0] if row else None
            try:
                ref = await self._secrets.put(conn, CONTEXT, url, existing)
            except SecretUnavailable:
                ref = await self._secrets.put(conn, CONTEXT, url, None)  # the old one cannot be read; replace it
            await conn.execute(
                "UPDATE calendar_feed SET secret_ref = %s, snapshot = NULL, status = %s WHERE id = 'owner'",
                (ref, Jsonb(FeedStatus(host=host).model_dump(mode="json"))),
            )

    async def clear(self) -> None:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("SELECT secret_ref FROM calendar_feed WHERE id = 'owner' FOR UPDATE")
            row = await cursor.fetchone()
            if row and row[0]:
                await self._secrets.delete(conn, CONTEXT, row[0])
            await conn.execute("UPDATE calendar_feed SET secret_ref = NULL, snapshot = NULL, status = '{}' WHERE id = 'owner'")

    async def save_config(self, config: FeedConfig) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE calendar_feed SET config = %s WHERE id = 'owner'", (Jsonb(config.model_dump(mode="json")),))

    async def save_overrides(self, overrides: dict[str, str]) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE calendar_feed SET overrides = %s WHERE id = 'owner'", (Jsonb(overrides),))

    async def save_snapshot(self, snapshot: Snapshot, status: FeedStatus) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE calendar_feed SET snapshot = %s, status = %s WHERE id = 'owner'",
                (Jsonb(snapshot.model_dump(mode="json")), Jsonb(status.model_dump(mode="json"))),
            )

    async def save_status(self, status: FeedStatus) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE calendar_feed SET status = %s WHERE id = 'owner'", (Jsonb(status.model_dump(mode="json")),))
