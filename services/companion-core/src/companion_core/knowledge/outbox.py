"""The indexing outbox (Phase 44B, docs/phase-44.md section 6). The database fills it: a trigger on each source table notes, in the
same transaction as the change, that "this source needs syncing". A row says only *which* source; the worker reads the source's
current state, so duplicates, replays and out-of-order processing all converge. There is one row per source. A change that arrives
while a row is being worked bumps its `gen`; the worker completes a row only if `gen` is unchanged, so no change is ever swallowed by
an in-flight sync. Leases expire, so a crashed worker's claim is retried. After MAX_ATTEMPTS a row is set aside as failed (visible in
the status) until a new change revives it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from psycopg_pool import AsyncConnectionPool

from shared.database import check_schema, connection_pool

MAX_ATTEMPTS = 8


def backoff(attempts: int) -> timedelta:
    """Wait before the next try after `attempts` failures: 1 minute, doubling, capped at one hour."""
    return timedelta(seconds=min(60 * 2 ** max(attempts - 1, 0), 3600))


@dataclass(frozen=True)
class OutboxItem:
    id: int
    source_type: str
    source_id: str
    gen: int
    attempts: int


@dataclass(frozen=True)
class OutboxStatus:
    pending: int
    failed: int
    oldest_pending_seconds: float | None


class Outbox(Protocol):
    async def enqueue(self, source_type: str, source_id: str, now: datetime) -> None: ...
    async def claim(self, now: datetime, *, lease_seconds: int, limit: int) -> list[OutboxItem]: ...
    async def complete(self, item: OutboxItem, now: datetime) -> bool: ...
    async def fail(self, item: OutboxItem, now: datetime, error: str) -> None: ...
    async def status(self, now: datetime) -> OutboxStatus: ...


@dataclass
class _Entry:
    id: int
    source_type: str
    source_id: str
    gen: int = 1
    attempts: int = 0
    enqueued_at: datetime | None = None
    next_attempt_at: datetime | None = None
    locked_until: datetime | None = None
    last_error: str | None = None
    failed: bool = False


class InMemoryOutbox:
    """Same behaviour as the Postgres outbox (including `gen`), for tests that do not need a database."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._next_id = 1

    async def enqueue(self, source_type: str, source_id: str, now: datetime) -> None:
        entry = self._entries.get((source_type, source_id))
        if entry is None:
            self._entries[(source_type, source_id)] = _Entry(
                self._next_id, source_type, source_id, enqueued_at=now, next_attempt_at=now
            )
            self._next_id += 1
        else:
            entry.gen += 1
            entry.next_attempt_at, entry.attempts, entry.failed, entry.last_error = now, 0, False, None

    async def claim(self, now: datetime, *, lease_seconds: int, limit: int) -> list[OutboxItem]:
        ready = sorted(
            (e for e in self._entries.values()
             if not e.failed and e.next_attempt_at <= now and (e.locked_until is None or e.locked_until <= now)),
            key=lambda e: (e.next_attempt_at, e.id),
        )[:limit]
        for e in ready:
            e.locked_until = now + timedelta(seconds=lease_seconds)
        return [OutboxItem(e.id, e.source_type, e.source_id, e.gen, e.attempts) for e in ready]

    async def complete(self, item: OutboxItem, now: datetime) -> bool:
        entry = self._entries.get((item.source_type, item.source_id))
        if entry is None or entry.id != item.id:
            return True
        if entry.gen != item.gen:  # something changed while this sync ran: leave it pending for another pass
            entry.locked_until, entry.next_attempt_at = None, now
            return False
        del self._entries[(item.source_type, item.source_id)]
        return True

    async def fail(self, item: OutboxItem, now: datetime, error: str) -> None:
        entry = self._entries.get((item.source_type, item.source_id))
        if entry is None or entry.id != item.id:
            return
        entry.attempts += 1
        entry.last_error, entry.locked_until = error[:200], None
        if entry.attempts >= MAX_ATTEMPTS:
            entry.failed = True
        else:
            entry.next_attempt_at = now + backoff(entry.attempts)

    async def status(self, now: datetime) -> OutboxStatus:
        pending = [e for e in self._entries.values() if not e.failed]
        oldest = min((e.enqueued_at for e in pending), default=None)
        return OutboxStatus(
            len(pending), sum(1 for e in self._entries.values() if e.failed),
            (now - oldest).total_seconds() if oldest else None,
        )


class PostgresOutbox:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresOutbox:
        pool = connection_pool(dsn, max_size=2)  # small on purpose; see PostgresKnowledgeIndex.connect
        await pool.open()
        async with pool.connection() as conn:
            await check_schema(conn)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def enqueue(self, source_type: str, source_id: str, now: datetime) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("SELECT knowledge_enqueue(%s, %s)", (source_type, source_id))

    async def claim(self, now: datetime, *, lease_seconds: int, limit: int) -> list[OutboxItem]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE knowledge_outbox SET locked_until = %s WHERE id IN ("
                "  SELECT id FROM knowledge_outbox WHERE failed_at IS NULL AND next_attempt_at <= %s "
                "  AND (locked_until IS NULL OR locked_until <= %s) ORDER BY next_attempt_at, id LIMIT %s FOR UPDATE SKIP LOCKED"
                ") RETURNING id, source_type, source_id, gen, attempts",
                (now + timedelta(seconds=lease_seconds), now, now, limit),
            )
            return [OutboxItem(*row) for row in await cur.fetchall()]

    async def complete(self, item: OutboxItem, now: datetime) -> bool:
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute("DELETE FROM knowledge_outbox WHERE id = %s AND gen = %s", (item.id, item.gen))
            if cur.rowcount:
                return True
            gone = await conn.execute("SELECT 1 FROM knowledge_outbox WHERE id = %s", (item.id,))
            if await gone.fetchone() is None:
                return True
            await conn.execute("UPDATE knowledge_outbox SET locked_until = NULL, next_attempt_at = %s WHERE id = %s", (now, item.id))
            return False

    async def fail(self, item: OutboxItem, now: datetime, error: str) -> None:
        attempts = item.attempts + 1
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE knowledge_outbox SET attempts = %s, last_error = %s, locked_until = NULL, "
                "failed_at = CASE WHEN %s::int >= %s::int THEN %s::timestamptz ELSE NULL END, next_attempt_at = %s WHERE id = %s AND gen = %s",
                (attempts, error[:200], attempts, MAX_ATTEMPTS, now, now + backoff(attempts), item.id, item.gen),
            )

    async def status(self, now: datetime) -> OutboxStatus:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) FILTER (WHERE failed_at IS NULL), count(*) FILTER (WHERE failed_at IS NOT NULL), "
                "min(enqueued_at) FILTER (WHERE failed_at IS NULL) FROM knowledge_outbox"
            )
            pending, failed, oldest = await cur.fetchone()
            return OutboxStatus(pending, failed, (now - oldest).total_seconds() if oldest else None)

