"""Postgres-backed PlannerStore. See store.py for the interface."""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg_pool import AsyncConnectionPool

from companion_core.planner.models import Note, Reminder, ReminderStatus
from shared.database import check_schema

_NOTE_COLUMNS = "id, title, body, created_at, updated_at"
_REMINDER_COLUMNS = "id, text, due_at, status, created_at, completed_at, notified_at"


def _note(row: tuple) -> Note:
    return Note(
        id=row[0], title=row[1], body=row[2], created_at=row[3], updated_at=row[4]
    )


def _reminder(row: tuple) -> Reminder:
    return Reminder(
        id=row[0],
        text=row[1],
        due_at=row[2],
        status=ReminderStatus(row[3]),
        created_at=row[4],
        completed_at=row[5],
        notified_at=row[6],
    )


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class PostgresPlannerStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresPlannerStore:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def list_notes(self, query: str | None = None) -> list[Note]:
        async with self._pool.connection() as conn:
            if query:
                cur = await conn.execute(
                    f"SELECT {_NOTE_COLUMNS} FROM notes WHERE title ILIKE %s OR body ILIKE %s "
                    "ORDER BY updated_at DESC",
                    (_like(query), _like(query)),
                )
            else:
                cur = await conn.execute(
                    f"SELECT {_NOTE_COLUMNS} FROM notes ORDER BY updated_at DESC"
                )
            return [_note(row) for row in await cur.fetchall()]

    async def add_note(self, title: str, body: str) -> Note:
        note = Note(title=title, body=body)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO notes ({_NOTE_COLUMNS}) VALUES (%s, %s, %s, %s, %s)",
                (note.id, note.title, note.body, note.created_at, note.updated_at),
            )
        return note

    async def update_note(self, note_id: str, title: str, body: str) -> Note | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE notes SET title = %s, body = %s, updated_at = %s WHERE id = %s RETURNING {_NOTE_COLUMNS}",
                (title, body, datetime.now(UTC), note_id),
            )
            row = await cur.fetchone()
            return _note(row) if row else None

    async def delete_note(self, note_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM notes WHERE id = %s", (note_id,))
            return cur.rowcount > 0

    async def list_reminders(self) -> list[Reminder]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_REMINDER_COLUMNS} FROM reminders ORDER BY due_at"
            )
            return [_reminder(row) for row in await cur.fetchall()]

    async def add_reminder(self, text: str, due_at: datetime) -> Reminder:
        reminder = Reminder(text=text, due_at=due_at)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO reminders ({_REMINDER_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    reminder.id,
                    reminder.text,
                    reminder.due_at,
                    reminder.status.value,
                    reminder.created_at,
                    reminder.completed_at,
                    reminder.notified_at,
                ),
            )
        return reminder

    async def complete_reminder(self, reminder_id: str) -> Reminder | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE reminders SET status = %s, completed_at = %s WHERE id = %s RETURNING {_REMINDER_COLUMNS}",
                (ReminderStatus.DONE.value, datetime.now(UTC), reminder_id),
            )
            row = await cur.fetchone()
            return _reminder(row) if row else None

    async def delete_reminder(self, reminder_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM reminders WHERE id = %s", (reminder_id,)
            )
            return cur.rowcount > 0

    async def claim_due(self, now: datetime) -> list[Reminder]:
        # One UPDATE ... RETURNING claims each reminder exactly once even if
        # two pollers overlap.
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE reminders SET notified_at = %s WHERE status = %s AND notified_at IS NULL "
                f"AND due_at <= %s RETURNING {_REMINDER_COLUMNS}",
                (now, ReminderStatus.PENDING.value, now),
            )
            return sorted(
                (_reminder(row) for row in await cur.fetchall()), key=lambda r: r.due_at
            )
