"""Postgres-backed TaskStore. See store.py for the interface."""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg_pool import AsyncConnectionPool

from companion_core.tasks.models import Task, TaskStatus

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
)
"""

_COLUMNS = "id, text, status, created_at, completed_at"


def _from_row(row: tuple) -> Task:
    return Task(id=row[0], text=row[1], status=TaskStatus(row[2]), created_at=row[3], completed_at=row[4])


class PostgresTaskStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresTaskStore:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def add_task(self, text: str) -> Task:
        task = Task(text=text)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO tasks ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s)",
                (task.id, task.text, task.status.value, task.created_at, task.completed_at),
            )
        return task

    async def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        async with self._pool.connection() as conn:
            if status is None:
                cur = await conn.execute(f"SELECT {_COLUMNS} FROM tasks ORDER BY created_at")
            else:
                cur = await conn.execute(
                    f"SELECT {_COLUMNS} FROM tasks WHERE status = %s ORDER BY created_at", (status.value,)
                )
            rows = await cur.fetchall()
            return [_from_row(row) for row in rows]

    async def complete_task(self, task_id: str) -> Task | None:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE tasks SET status = %s, completed_at = %s WHERE id = %s RETURNING {_COLUMNS}",
                (TaskStatus.DONE.value, now, task_id),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def search_tasks(self, query: str) -> list[Task]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM tasks WHERE text ILIKE %s ORDER BY created_at", (f"%{query}%",)
            )
            rows = await cur.fetchall()
            return [_from_row(row) for row in rows]
