"""PostgreSQL store for Phase 31 (migration 032). Every transition is a single guarded UPDATE or a transaction, so concurrent requests, retries and a crash cannot create a
second active run, a second item for one quoted sentence, or a second task."""

from __future__ import annotations

from datetime import datetime, timedelta

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from companion_core.meeting_analysis.models import (
    ACCEPTING_STALE_SECONDS,
    LEASE_SECONDS,
    Item,
    ItemStatus,
    Run,
    same_finding,
)
from companion_core.meeting_analysis.store import Claim, Decision
from shared.database import check_schema, close_pool, open_pool
from shared.models.response import Privacy

_RUN = ("id, meeting_id, meeting_title, transcript_hash, segments, meeting_started_at, timezone, sensitivity, project_scope, status, attempts, error, model, reprocess, item_count, rejected, "
        "inputs_hash, created_at, started_at, finished_at, lease_until")
_ITEM = ("id, run_id, meeting_id, transcript_hash, kind, text, evidence, assignee, stated_time, due_at, ambiguity, support, status, fingerprint, model, prompt_version, sensitivity, project_scope, "
         "final_text, edited, record_kind, record_id, created_at, accepting_at, decided_at")


def _run(row) -> Run:
    return Run(**dict(zip((k.strip() for k in _RUN.split(",")), row, strict=True)))


def _item(row) -> Item:
    return Item(**dict(zip((k.strip() for k in _ITEM.split(",")), row, strict=True)))


class PostgresMeetingAnalysisStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, source) -> PostgresMeetingAnalysisStore:
        pool = await open_pool(source)
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await close_pool(self._pool)

    async def enqueue(self, run: Run, *, force: bool) -> tuple[Run, bool]:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(f"SELECT {_RUN} FROM meeting_analysis_runs WHERE meeting_id = %s AND status IN ('queued', 'processing')", (run.meeting_id,))).fetchone()
            if row:
                return _run(row), False
            if not force:
                row = await (await conn.execute(
                    f"SELECT {_RUN} FROM meeting_analysis_runs WHERE meeting_id = %s AND inputs_hash = %s AND status = 'succeeded' ORDER BY created_at DESC LIMIT 1",
                    (run.meeting_id, run.inputs_hash))).fetchone()
                if row:
                    return _run(row), False
            cursor = await conn.execute(
                f"INSERT INTO meeting_analysis_runs ({_RUN}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (meeting_id) WHERE status IN ('queued', 'processing') DO NOTHING RETURNING id",
                (run.id, run.meeting_id, run.meeting_title, run.transcript_hash, Jsonb([s.model_dump(mode="json") for s in run.segments]), run.meeting_started_at, run.timezone,
                 run.sensitivity.value, run.project_scope, run.status.value, run.attempts, run.error, run.model, run.reprocess, run.item_count, Jsonb(run.rejected), run.inputs_hash,
                 run.created_at, run.started_at, run.finished_at, run.lease_until))
            if await cursor.fetchone():
                return run, True
            row = await (await conn.execute(f"SELECT {_RUN} FROM meeting_analysis_runs WHERE meeting_id = %s AND status IN ('queued', 'processing')", (run.meeting_id,))).fetchone()
            return _run(row), False  # a concurrent request inserted the active run first

    async def get_run(self, run_id: str) -> Run | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_RUN} FROM meeting_analysis_runs WHERE id = %s", (run_id,))).fetchone()
        return _run(row) if row else None

    async def latest_run(self, meeting_id: str) -> Run | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_RUN} FROM meeting_analysis_runs WHERE meeting_id = %s ORDER BY created_at DESC LIMIT 1", (meeting_id,))).fetchone()
        return _run(row) if row else None

    async def claim_next(self, now: datetime) -> Run | None:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                "UPDATE meeting_analysis_runs SET status = 'processing', attempts = attempts + 1, started_at = %s, lease_until = %s WHERE id = ("
                "SELECT id FROM meeting_analysis_runs WHERE status = 'queued' OR (status = 'processing' AND lease_until <= %s) ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                f") RETURNING {_RUN}", (now, now + timedelta(seconds=LEASE_SECONDS), now))).fetchone()
        return _run(row) if row else None

    async def complete_run(self, run_id: str, items: list[Item], *, model: str, rejected: dict[str, int], now: datetime) -> int:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute("SELECT meeting_id FROM meeting_analysis_runs WHERE id = %s AND status = 'processing' FOR UPDATE", (run_id,))).fetchone()
            if row is None:
                return 0
            held = [_item(r) for r in await (await conn.execute(f"SELECT {_ITEM} FROM meeting_analysis_items WHERE meeting_id = %s", (row[0],))).fetchall()]
            added = 0
            for i in items:
                match = next((h for h in held if h.fingerprint == i.fingerprint or same_finding(h, i)), None)
                if match is not None:
                    # Already extracted, accepted or dismissed: re-analysis never brings it back, however the model words or extends the quote. An item the owner has not decided is
                    # refreshed from the new run, so its evidence matches the transcript as it reads now (after corrections); a decided one is left exactly as it was.
                    if match.status in (ItemStatus.PENDING, ItemStatus.NOTED):
                        await conn.execute(
                            "UPDATE meeting_analysis_items SET run_id = %s, transcript_hash = %s, text = %s, evidence = %s, assignee = %s, stated_time = %s, due_at = %s, ambiguity = %s, support = %s, "
                            "model = %s, prompt_version = %s WHERE id = %s AND status IN ('pending', 'noted')",
                            (i.run_id, i.transcript_hash, i.text, Jsonb([e.model_dump(mode="json") for e in i.evidence]), i.assignee, i.stated_time, i.due_at, Jsonb(i.ambiguity), i.support.value,
                             i.model, i.prompt_version, match.id))
                    continue
                cursor = await conn.execute(
                    f"INSERT INTO meeting_analysis_items ({_ITEM}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
                    (i.id, i.run_id, i.meeting_id, i.transcript_hash, i.kind.value, i.text, Jsonb([e.model_dump(mode="json") for e in i.evidence]), i.assignee, i.stated_time, i.due_at,
                     Jsonb(i.ambiguity), i.support.value, i.status.value, i.fingerprint, i.model, i.prompt_version, i.sensitivity.value, i.project_scope, None, False, None, None, i.created_at, None, None))
                if await cursor.fetchone():
                    held.append(i)
                    added += 1
            await conn.execute("UPDATE meeting_analysis_runs SET status = 'succeeded', model = %s, item_count = %s, rejected = %s, finished_at = %s, lease_until = NULL, error = NULL WHERE id = %s",
                               (model, added, Jsonb(rejected), now, run_id))
            return added

    async def fail_run(self, run_id: str, error: str, *, now: datetime) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE meeting_analysis_runs SET status = 'failed', error = %s, finished_at = %s, lease_until = NULL WHERE id = %s AND status = 'processing'", (error, now, run_id))

    async def retry_run(self, run_id: str, *, now: datetime) -> tuple[Run | None, str]:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(f"SELECT {_RUN} FROM meeting_analysis_runs WHERE id = %s FOR UPDATE", (run_id,))).fetchone()
            if row is None:
                return None, "missing"
            run = _run(row)
            if run.status.value != "failed":
                return run, "not_failed"
            if await (await conn.execute("SELECT 1 FROM meeting_analysis_runs WHERE meeting_id = %s AND status IN ('queued', 'processing')", (run.meeting_id,))).fetchone():
                return run, "active"
            row = await (await conn.execute(f"UPDATE meeting_analysis_runs SET status = 'queued', error = NULL, finished_at = NULL WHERE id = %s RETURNING {_RUN}", (run_id,))).fetchone()
            return _run(row), "queued"

    async def list_items(self, *, meeting_id: str | None = None, statuses: tuple[ItemStatus, ...] | None = None) -> list[Item]:
        clauses, args = [], []
        if meeting_id is not None:
            clauses.append("meeting_id = %s")
            args.append(meeting_id)
        if statuses is not None:
            clauses.append("status = ANY(%s)")
            args.append([s.value for s in statuses])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                f"SELECT {_ITEM} FROM meeting_analysis_items {where} ORDER BY (evidence->0->>'start')::double precision, created_at, kind", args)).fetchall()
        return [_item(r) for r in rows]

    async def get_item(self, item_id: str) -> Item | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_analysis_items WHERE id = %s", (item_id,))).fetchone()
        return _item(row) if row else None

    async def item_for_record(self, record_id: str) -> Item | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_analysis_items WHERE record_id = %s", (record_id,))).fetchone()
        return _item(row) if row else None

    async def claim_accept(self, item_id: str, *, text: str, sensitivity: Privacy, edited: bool, now: datetime) -> Claim:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                "UPDATE meeting_analysis_items SET status = 'accepting', final_text = %s, sensitivity = %s, edited = %s, accepting_at = %s "
                f"WHERE id = %s AND status = 'pending' RETURNING {_ITEM}", (text, sensitivity.value, edited, now, item_id))).fetchone()
            if row:
                return Claim("claimed", _item(row))
            current = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_analysis_items WHERE id = %s FOR UPDATE", (item_id,))).fetchone()
            if current is None:
                return Claim("missing")
            i = _item(current)
            if i.status is ItemStatus.ACCEPTED:
                return Claim("done", i)
            if i.status is ItemStatus.ACCEPTING:
                if i.accepting_at is not None and (now - i.accepting_at).total_seconds() < ACCEPTING_STALE_SECONDS:
                    return Claim("in_progress", i)
                row = await (await conn.execute(f"UPDATE meeting_analysis_items SET accepting_at = %s WHERE id = %s AND status = 'accepting' RETURNING {_ITEM}", (now, item_id))).fetchone()
                return Claim("claimed", _item(row))
            return Claim("closed", i)

    async def finish_accept(self, item_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Item | None:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                "UPDATE meeting_analysis_items SET status = 'accepted', record_kind = %s, record_id = %s, decided_at = %s "
                f"WHERE id = %s AND status = 'accepting' RETURNING {_ITEM}", (record_kind, record_id, now, item_id))).fetchone()
            if row:
                return _item(row)
            row = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_analysis_items WHERE id = %s AND status = 'accepted'", (item_id,))).fetchone()
        return _item(row) if row else None

    async def dismiss(self, item_id: str, *, now: datetime) -> Decision:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"UPDATE meeting_analysis_items SET status = 'dismissed', decided_at = %s WHERE id = %s AND status IN ('pending', 'noted') RETURNING {_ITEM}", (now, item_id))).fetchone()
            if row:
                return Decision("done", _item(row))
            current = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_analysis_items WHERE id = %s", (item_id,))).fetchone()
        if current is None:
            return Decision("missing")
        i = _item(current)
        return Decision("already" if i.status is ItemStatus.DISMISSED else "closed", i)

    async def stale_accepting(self, now: datetime) -> list[str]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute("SELECT id FROM meeting_analysis_items WHERE status = 'accepting' AND (accepting_at IS NULL OR accepting_at <= %s)",
                                             (now - timedelta(seconds=ACCEPTING_STALE_SECONDS),))).fetchall()
        return [r[0] for r in rows]

    async def drop_meeting(self, meeting_id: str) -> int:
        async with self._pool.connection() as conn, conn.transaction():
            cursor = await conn.execute("DELETE FROM meeting_analysis_items WHERE meeting_id = %s", (meeting_id,))
            await conn.execute("DELETE FROM meeting_analysis_runs WHERE meeting_id = %s", (meeting_id,))
            return cursor.rowcount
