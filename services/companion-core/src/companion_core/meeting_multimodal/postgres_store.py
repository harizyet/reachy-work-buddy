"""PostgreSQL store for Phase 53 (migration 034). Every transition is a single guarded UPDATE or a transaction, so concurrent requests, retries and a crash cannot create a second active
run, a second link, a second finding for one quoted sentence, or a second task. Same shapes and guarantees as Phase 31's store."""

from __future__ import annotations

from datetime import datetime, timedelta

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from companion_core.meeting_multimodal.models import (
    ACCEPTING_STALE_SECONDS,
    LEASE_SECONDS,
    Alignment,
    Item,
    ItemStatus,
    Link,
    Review,
    Run,
    RunKind,
)
from companion_core.meeting_multimodal.store import (
    Claim,
    Decision,
    merge_items,
    strip_document,
)
from shared.database import check_schema, close_pool, open_pool
from shared.models.response import Privacy

_LINK = "meeting_id, document_id, link_status, linked_by, created_at, updated_at"
_RUN = "id, meeting_id, kind, status, ceiling, transcript_hash, doc_revisions, inputs_hash, attempts, error, model, force, stats, created_at, started_at, finished_at, lease_until"
_ALIGN = ("id, run_id, meeting_id, window_key, segment_ids, start_s, end_s, document_id, page, locator, slide_title, alternatives, certainty, method, relation, reason, model_note, shared_terms, "
          "explicit_refs, contradictions, unchecked, transcript_revision, document_revision, analysis_version, model, sensitivity, project_scope, created_at")
_REVIEW = "meeting_id, window_key, decision, document_id, page, rejected_document_id, rejected_page, transcript_revision, document_revision, created_at, updated_at"
_ITEM = ("id, run_id, meeting_id, transcript_hash, kind, text, evidence, assignee, stated_time, ambiguity, support, status, fingerprint, model, prompt_version, sensitivity, project_scope, "
         "final_text, edited, record_kind, record_id, created_at, accepting_at, decided_at")


def _cols(columns: str, row) -> dict:
    return dict(zip((k.strip() for k in columns.split(",")), row, strict=True))


def _link(row) -> Link:
    return Link(**_cols(_LINK, row))


def _run(row) -> Run:
    return Run(**_cols(_RUN, row))


def _review(row) -> Review:
    return Review(**_cols(_REVIEW, row))


def _item(row) -> Item:
    return Item(**_cols(_ITEM, row))


def _alignment(row) -> Alignment:
    data = _cols(_ALIGN, row)
    data["start"], data["end"] = data.pop("start_s"), data.pop("end_s")
    return Alignment(**data)


def _marks(n: int) -> str:
    return ",".join(["%s"] * n)


class PostgresMultimodalStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, source) -> PostgresMultimodalStore:
        pool = await open_pool(source)
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await close_pool(self._pool)

    # -- links --------------------------------------------------------------------------------------------------------------

    async def add_link(self, link: Link) -> tuple[Link, bool]:
        async with self._pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                f"INSERT INTO meeting_document_links ({_LINK}) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (meeting_id, document_id) DO NOTHING RETURNING meeting_id",
                (link.meeting_id, link.document_id, link.link_status, link.linked_by, link.created_at, link.updated_at))
            if await cursor.fetchone():
                return link, True
            row = await (await conn.execute(f"SELECT {_LINK} FROM meeting_document_links WHERE meeting_id = %s AND document_id = %s", (link.meeting_id, link.document_id))).fetchone()
            return _link(row), False

    async def remove_link(self, meeting_id: str, document_id: str) -> bool:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("DELETE FROM meeting_document_links WHERE meeting_id = %s AND document_id = %s", (meeting_id, document_id))
            return cursor.rowcount > 0

    async def list_links(self, meeting_id: str) -> list[Link]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_LINK} FROM meeting_document_links WHERE meeting_id = %s ORDER BY created_at, document_id", (meeting_id,))).fetchall()
        return [_link(r) for r in rows]

    # -- runs ---------------------------------------------------------------------------------------------------------------

    async def enqueue(self, run: Run, *, force: bool) -> tuple[Run, bool]:
        active = f"SELECT {_RUN} FROM meeting_multimodal_runs WHERE meeting_id = %s AND kind = %s AND status IN ('queued', 'processing')"
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(active, (run.meeting_id, run.kind.value))).fetchone()
            if row:
                return _run(row), False
            if not force:
                row = await (await conn.execute(
                    f"SELECT {_RUN} FROM meeting_multimodal_runs WHERE meeting_id = %s AND kind = %s AND inputs_hash = %s AND status = 'succeeded' ORDER BY created_at DESC LIMIT 1",
                    (run.meeting_id, run.kind.value, run.inputs_hash))).fetchone()
                if row:
                    return _run(row), False
            cursor = await conn.execute(
                f"INSERT INTO meeting_multimodal_runs ({_RUN}) VALUES ({_marks(17)}) ON CONFLICT (meeting_id, kind) WHERE status IN ('queued', 'processing') DO NOTHING RETURNING id",
                (run.id, run.meeting_id, run.kind.value, run.status.value, run.ceiling.value, run.transcript_hash, Jsonb(run.doc_revisions), run.inputs_hash, run.attempts, run.error, run.model,
                 run.force, Jsonb(run.stats), run.created_at, run.started_at, run.finished_at, run.lease_until))
            if await cursor.fetchone():
                return run, True
            row = await (await conn.execute(active, (run.meeting_id, run.kind.value))).fetchone()
            return _run(row), False  # a concurrent request inserted the active run first

    async def get_run(self, run_id: str) -> Run | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_RUN} FROM meeting_multimodal_runs WHERE id = %s", (run_id,))).fetchone()
        return _run(row) if row else None

    async def latest_run(self, meeting_id: str, kind: RunKind) -> Run | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                f"SELECT {_RUN} FROM meeting_multimodal_runs WHERE meeting_id = %s AND kind = %s ORDER BY created_at DESC LIMIT 1", (meeting_id, kind.value))).fetchone()
        return _run(row) if row else None

    async def claim_next(self, now: datetime) -> Run | None:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                "UPDATE meeting_multimodal_runs SET status = 'processing', attempts = attempts + 1, started_at = %s, lease_until = %s WHERE id = ("
                "SELECT id FROM meeting_multimodal_runs WHERE status = 'queued' OR (status = 'processing' AND lease_until <= %s) ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                f") RETURNING {_RUN}", (now, now + timedelta(seconds=LEASE_SECONDS), now))).fetchone()
        return _run(row) if row else None

    async def requeue_processing(self) -> int:
        async with self._pool.connection() as conn:
            return (await conn.execute("UPDATE meeting_multimodal_runs SET status = 'queued', lease_until = NULL WHERE status = 'processing'")).rowcount

    async def _processing_meeting(self, conn, run_id: str) -> str | None:
        row = await (await conn.execute("SELECT meeting_id FROM meeting_multimodal_runs WHERE id = %s AND status = 'processing' FOR UPDATE", (run_id,))).fetchone()
        return row[0] if row else None

    async def _succeed(self, conn, run_id: str, model: str, stats: dict, now: datetime) -> None:
        await conn.execute("UPDATE meeting_multimodal_runs SET status = 'succeeded', model = %s, stats = %s, finished_at = %s, lease_until = NULL, error = NULL WHERE id = %s",
                           (model, Jsonb(stats), now, run_id))

    async def complete_alignment(self, run_id: str, alignments: list[Alignment], *, model: str, stats: dict, now: datetime) -> int:
        async with self._pool.connection() as conn, conn.transaction():
            meeting_id = await self._processing_meeting(conn, run_id)
            if meeting_id is None:
                return 0
            await conn.execute("DELETE FROM meeting_slide_alignments WHERE meeting_id = %s", (meeting_id,))  # the previous run's estimates; the owner's reviews are a different table
            for a in alignments:
                await conn.execute(
                    f"INSERT INTO meeting_slide_alignments ({_ALIGN}) VALUES ({_marks(28)})",
                    (a.id, a.run_id, a.meeting_id, a.window_key, Jsonb(a.segment_ids), a.start, a.end, a.document_id, a.page, a.locator, a.slide_title,
                     Jsonb([x.model_dump(mode="json") for x in a.alternatives]), a.certainty.value, a.method.value, a.relation.value, a.reason, a.model_note, Jsonb(a.shared_terms),
                     Jsonb(a.explicit_refs), Jsonb([x.model_dump(mode="json") for x in a.contradictions]), a.unchecked, a.transcript_revision, a.document_revision, a.analysis_version, a.model,
                     a.sensitivity.value, a.project_scope, a.created_at))
            await self._succeed(conn, run_id, model, stats, now)
            return len(alignments)

    async def complete_analysis(self, run_id: str, items: list[Item], *, model: str, stats: dict, now: datetime) -> int:
        async with self._pool.connection() as conn, conn.transaction():
            meeting_id = await self._processing_meeting(conn, run_id)
            if meeting_id is None:
                return 0
            held = [_item(r) for r in await (await conn.execute(f"SELECT {_ITEM} FROM meeting_multimodal_items WHERE meeting_id = %s", (meeting_id,))).fetchall()]
            insert, refresh = merge_items(held, items)
            for match, fresh in refresh:
                await conn.execute(
                    "UPDATE meeting_multimodal_items SET run_id = %s, transcript_hash = %s, text = %s, evidence = %s, assignee = %s, stated_time = %s, ambiguity = %s, support = %s, "
                    "model = %s, prompt_version = %s, sensitivity = %s WHERE id = %s AND status IN ('pending', 'noted')",
                    (fresh.run_id, fresh.transcript_hash, fresh.text, Jsonb([c.model_dump(mode="json") for c in fresh.evidence]), fresh.assignee, fresh.stated_time, Jsonb(fresh.ambiguity),
                     fresh.support.value, fresh.model, fresh.prompt_version, fresh.sensitivity.value, match.id))
            added = 0
            for i in insert:
                cursor = await conn.execute(
                    f"INSERT INTO meeting_multimodal_items ({_ITEM}) VALUES ({_marks(24)}) ON CONFLICT DO NOTHING RETURNING id",
                    (i.id, i.run_id, i.meeting_id, i.transcript_hash, i.kind.value, i.text, Jsonb([c.model_dump(mode="json") for c in i.evidence]), i.assignee, i.stated_time, Jsonb(i.ambiguity),
                     i.support.value, i.status.value, i.fingerprint, i.model, i.prompt_version, i.sensitivity.value, i.project_scope, None, False, None, None, i.created_at, None, None))
                added += 1 if await cursor.fetchone() else 0
            await self._succeed(conn, run_id, model, {**stats, "items": added}, now)
            return added

    async def fail_run(self, run_id: str, error: str, *, now: datetime) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE meeting_multimodal_runs SET status = 'failed', error = %s, finished_at = %s, lease_until = NULL WHERE id = %s AND status = 'processing'", (error, now, run_id))

    async def retry_run(self, run_id: str, *, now: datetime) -> tuple[Run | None, str]:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(f"SELECT {_RUN} FROM meeting_multimodal_runs WHERE id = %s FOR UPDATE", (run_id,))).fetchone()
            if row is None:
                return None, "missing"
            run = _run(row)
            if run.status.value != "failed":
                return run, "not_failed"
            if await (await conn.execute("SELECT 1 FROM meeting_multimodal_runs WHERE meeting_id = %s AND kind = %s AND status IN ('queued', 'processing')", (run.meeting_id, run.kind.value))).fetchone():
                return run, "active"
            row = await (await conn.execute(f"UPDATE meeting_multimodal_runs SET status = 'queued', error = NULL, finished_at = NULL WHERE id = %s RETURNING {_RUN}", (run_id,))).fetchone()
            return _run(row), "queued"

    # -- alignments and reviews ---------------------------------------------------------------------------------------------

    async def list_alignments(self, meeting_id: str) -> list[Alignment]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_ALIGN} FROM meeting_slide_alignments WHERE meeting_id = %s ORDER BY start_s, window_key", (meeting_id,))).fetchall()
        return [_alignment(r) for r in rows]

    async def set_review(self, review: Review) -> Review:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                f"INSERT INTO meeting_slide_reviews ({_REVIEW}) VALUES ({_marks(11)}) ON CONFLICT (meeting_id, window_key) DO UPDATE SET decision = EXCLUDED.decision, "
                "document_id = EXCLUDED.document_id, page = EXCLUDED.page, rejected_document_id = EXCLUDED.rejected_document_id, rejected_page = EXCLUDED.rejected_page, "
                f"transcript_revision = EXCLUDED.transcript_revision, document_revision = EXCLUDED.document_revision, updated_at = EXCLUDED.updated_at RETURNING {_REVIEW}",
                (review.meeting_id, review.window_key, review.decision.value, review.document_id, review.page, review.rejected_document_id, review.rejected_page, review.transcript_revision,
                 review.document_revision, review.created_at, review.updated_at))).fetchone()
        return _review(row)

    async def clear_review(self, meeting_id: str, window_key: str) -> bool:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("DELETE FROM meeting_slide_reviews WHERE meeting_id = %s AND window_key = %s", (meeting_id, window_key))
            return cursor.rowcount > 0

    async def list_reviews(self, meeting_id: str) -> list[Review]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_REVIEW} FROM meeting_slide_reviews WHERE meeting_id = %s ORDER BY window_key", (meeting_id,))).fetchall()
        return [_review(r) for r in rows]

    # -- items --------------------------------------------------------------------------------------------------------------

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
                f"SELECT {_ITEM} FROM meeting_multimodal_items {where} ORDER BY COALESCE((evidence->0->>'start')::double precision, 0), created_at, kind", args)).fetchall()
        return [_item(r) for r in rows]

    async def get_item(self, item_id: str) -> Item | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_multimodal_items WHERE id = %s", (item_id,))).fetchone()
        return _item(row) if row else None

    async def item_for_record(self, record_id: str) -> Item | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_multimodal_items WHERE record_id = %s", (record_id,))).fetchone()
        return _item(row) if row else None

    async def claim_accept(self, item_id: str, *, text: str, sensitivity: Privacy, edited: bool, now: datetime) -> Claim:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                "UPDATE meeting_multimodal_items SET status = 'accepting', final_text = %s, sensitivity = %s, edited = %s, accepting_at = %s "
                f"WHERE id = %s AND status = 'pending' RETURNING {_ITEM}", (text, sensitivity.value, edited, now, item_id))).fetchone()
            if row:
                return Claim("claimed", _item(row))
            current = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_multimodal_items WHERE id = %s FOR UPDATE", (item_id,))).fetchone()
            if current is None:
                return Claim("missing")
            i = _item(current)
            if i.status is ItemStatus.ACCEPTED:
                return Claim("done", i)
            if i.status is ItemStatus.ACCEPTING:
                if i.accepting_at is not None and (now - i.accepting_at).total_seconds() < ACCEPTING_STALE_SECONDS:
                    return Claim("in_progress", i)
                row = await (await conn.execute(f"UPDATE meeting_multimodal_items SET accepting_at = %s WHERE id = %s AND status = 'accepting' RETURNING {_ITEM}", (now, item_id))).fetchone()
                return Claim("claimed", _item(row))
            return Claim("closed", i)

    async def finish_accept(self, item_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Item | None:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                "UPDATE meeting_multimodal_items SET status = 'accepted', record_kind = %s, record_id = %s, decided_at = %s "
                f"WHERE id = %s AND status = 'accepting' RETURNING {_ITEM}", (record_kind, record_id, now, item_id))).fetchone()
            if row:
                return _item(row)
            row = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_multimodal_items WHERE id = %s AND status = 'accepted'", (item_id,))).fetchone()
        return _item(row) if row else None

    async def dismiss(self, item_id: str, *, now: datetime) -> Decision:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"UPDATE meeting_multimodal_items SET status = 'dismissed', decided_at = %s WHERE id = %s AND status IN ('pending', 'noted') RETURNING {_ITEM}", (now, item_id))).fetchone()
            if row:
                return Decision("done", _item(row))
            current = await (await conn.execute(f"SELECT {_ITEM} FROM meeting_multimodal_items WHERE id = %s", (item_id,))).fetchone()
        if current is None:
            return Decision("missing")
        i = _item(current)
        return Decision("already" if i.status is ItemStatus.DISMISSED else "closed", i)

    async def stale_accepting(self, now: datetime) -> list[str]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute("SELECT id FROM meeting_multimodal_items WHERE status = 'accepting' AND (accepting_at IS NULL OR accepting_at <= %s)",
                                             (now - timedelta(seconds=ACCEPTING_STALE_SECONDS),))).fetchall()
        return [r[0] for r in rows]

    # -- lifecycle ----------------------------------------------------------------------------------------------------------

    async def drop_meeting(self, meeting_id: str) -> int:
        async with self._pool.connection() as conn, conn.transaction():
            n = 0
            for table in ("meeting_document_links", "meeting_slide_alignments", "meeting_slide_reviews", "meeting_multimodal_items", "meeting_multimodal_runs"):
                n += (await conn.execute(f"DELETE FROM {table} WHERE meeting_id = %s", (meeting_id,))).rowcount
            return n

    async def drop_document(self, document_id: str, *, meeting_id: str | None = None) -> int:
        scope, args = ("AND meeting_id = %s", (meeting_id,)) if meeting_id is not None else ("", ())
        async with self._pool.connection() as conn, conn.transaction():
            n = (await conn.execute(f"DELETE FROM meeting_document_links WHERE document_id = %s {scope}", (document_id, *args))).rowcount
            n += (await conn.execute(f"DELETE FROM meeting_slide_alignments WHERE document_id = %s {scope}", (document_id, *args))).rowcount
            await conn.execute(
                "UPDATE meeting_slide_alignments SET alternatives = COALESCE((SELECT jsonb_agg(a) FROM jsonb_array_elements(alternatives) a WHERE a->>'document_id' <> %s), '[]'::jsonb) "
                f"WHERE alternatives @> %s::jsonb {scope}", (document_id, Jsonb([{"document_id": document_id}]), *args))
            n += (await conn.execute(f"DELETE FROM meeting_slide_reviews WHERE (document_id = %s OR rejected_document_id = %s) {scope}", (document_id, document_id, *args))).rowcount
            rows = await (await conn.execute(
                f"SELECT {_ITEM} FROM meeting_multimodal_items WHERE evidence @> %s::jsonb {scope} FOR UPDATE", (Jsonb([{"document_id": document_id}]), *args))).fetchall()
            for item in (_item(r) for r in rows):
                kept = strip_document(item, document_id)
                if kept is None:
                    await conn.execute("DELETE FROM meeting_multimodal_items WHERE id = %s", (item.id,))
                else:
                    await conn.execute("UPDATE meeting_multimodal_items SET evidence = %s WHERE id = %s", (Jsonb([c.model_dump(mode="json") for c in kept.evidence]), item.id))
                n += 1
            await conn.execute(f"UPDATE meeting_multimodal_runs SET doc_revisions = doc_revisions - %s WHERE doc_revisions ? %s {scope}", (document_id, document_id, *args))
            return n
