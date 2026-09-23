"""Postgres-backed CalendarStore. See store.py for the interface.

The working default for Phase 10 (see the phase's own decision on this: no
external calendar credential was available, so this local store is real
and durable rather than a stub) — a real Google Calendar/CalDAV provider
implements the same CalendarStore protocol later without any caller
changing.
"""

from __future__ import annotations

from datetime import datetime

from psycopg_pool import AsyncConnectionPool

from companion_core.calendar.models import CalendarEvent
from shared.database import check_schema

_COLUMNS = "id, title, start_at, end_at, location"


def _from_row(row: tuple) -> CalendarEvent:
    return CalendarEvent(id=row[0], title=row[1], start=row[2], end=row[3], location=row[4])


class PostgresCalendarStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresCalendarStore:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def add_event(self, event: CalendarEvent) -> CalendarEvent:
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO calendar_events ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s)",
                (event.id, event.title, event.start, event.end, event.location),
            )
        return event

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM calendar_events "
                "WHERE start_at < %s AND end_at > %s ORDER BY start_at",
                (end, start),
            )
            rows = await cur.fetchall()
            return [_from_row(row) for row in rows]

    async def next_event(self, after: datetime) -> CalendarEvent | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM calendar_events WHERE start_at >= %s ORDER BY start_at LIMIT 1",
                (after,),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None
