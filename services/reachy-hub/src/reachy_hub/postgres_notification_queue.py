"""Postgres-backed NotificationQueue. See notification_queue.py for the
interface."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from psycopg_pool import AsyncConnectionPool

from reachy_hub.notification_queue import QueuedNotification
from shared.models.response import Privacy, Urgency

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notification_queue (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    privacy TEXT NOT NULL,
    urgency TEXT NOT NULL,
    source_event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS notification_queue_user_id_idx ON notification_queue (user_id)
"""

_COLUMNS = "id, user_id, text, privacy, urgency, source_event_id, created_at"


def _from_row(row: tuple) -> QueuedNotification:
    return QueuedNotification(
        id=row[0],
        user_id=row[1],
        text=row[2],
        privacy=Privacy(row[3]),
        urgency=Urgency(row[4]),
        source_event_id=row[5],
        created_at=row[6],
    )


class PostgresNotificationQueue:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresNotificationQueue:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
            await conn.execute(_CREATE_INDEX_SQL)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def enqueue(
        self,
        *,
        user_id: str,
        text: str,
        privacy: Privacy,
        urgency: Urgency,
        source_event_id: str | None,
    ) -> QueuedNotification:
        notification = QueuedNotification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            text=text,
            privacy=privacy,
            urgency=urgency,
            source_event_id=source_event_id,
            created_at=datetime.now(UTC),
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO notification_queue ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    notification.id,
                    notification.user_id,
                    notification.text,
                    notification.privacy.value,
                    notification.urgency.value,
                    notification.source_event_id,
                    notification.created_at,
                ),
            )
        return notification

    async def list_for_user(self, user_id: str) -> list[QueuedNotification]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM notification_queue WHERE user_id = %s ORDER BY created_at", (user_id,)
            )
            rows = await cur.fetchall()
            return [_from_row(row) for row in rows]

    async def clear_for_user(self, user_id: str) -> list[QueuedNotification]:
        notifications = await self.list_for_user(user_id)
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM notification_queue WHERE user_id = %s", (user_id,))
        return notifications
