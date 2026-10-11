"""PostgreSQL store for Phase 49 (migration 029). Every transition is a single guarded UPDATE or a transaction, so concurrent requests, retries and a crash cannot
create a second job, a second proposal for a source sentence, or a second record."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from companion_core.notepad_processing.models import (
    ACCEPTING_STALE_SECONDS,
    LEASE_SECONDS,
    Job,
    Kind,
    MeetingLink,
    Proposal,
    ProposalStatus,
    Provenance,
)
from companion_core.notepad_processing.store import Claim, Decision
from shared.database import check_schema, close_pool, open_pool
from shared.models.response import Privacy

_JOB = ("id, note_id, note_title, snapshot_text, snapshot_hash, note_updated_at, timezone, sensitivity, project_scope, status, attempts, error, model, reprocess, "
        "proposal_count, inputs_hash, sources, created_at, started_at, finished_at, lease_until")
_PROP = ("id, job_id, note_id, snapshot_hash, kind, text, evidence, span_start, span_end, sources, evidence_from, source_key, stated_time, due_at, ambiguity, status, fingerprint, model, prompt_version, "
         "sensitivity, project_scope, final_kind, final_text, final_due_at, edited, record_kind, record_id, created_at, accepting_at, decided_at")


_LINK = "id, note_id, meeting_id, source, state, overlap_seconds, title_match, created_at, updated_at, decided_at"


def _link(row) -> MeetingLink:
    keys = [k.strip() for k in _LINK.split(",")]
    return MeetingLink(**dict(zip(keys, row, strict=True)))


def _job(row) -> Job:
    keys = [k.strip() for k in _JOB.split(",")]
    return Job(**dict(zip(keys, row, strict=True)))


def _proposal(row) -> Proposal:
    keys = [k.strip() for k in _PROP.split(",")]
    return Proposal(**dict(zip(keys, row, strict=True)))


class PostgresNotepadStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, source) -> PostgresNotepadStore:
        pool = await open_pool(source)
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await close_pool(self._pool)

    async def enqueue(self, job: Job, *, force: bool) -> tuple[Job, bool]:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(f"SELECT {_JOB} FROM notepad_jobs WHERE note_id = %s AND status IN ('queued', 'processing')", (job.note_id,))).fetchone()
            if row:
                return _job(row), False
            if not force:
                row = await (await conn.execute(
                    f"SELECT {_JOB} FROM notepad_jobs WHERE note_id = %s AND inputs_hash = %s AND status = 'succeeded' ORDER BY created_at DESC LIMIT 1",
                    (job.note_id, job.inputs_hash))).fetchone()
                if row:
                    return _job(row), False
            cursor = await conn.execute(
                f"INSERT INTO notepad_jobs ({_JOB}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (note_id) WHERE status IN ('queued', 'processing') DO NOTHING RETURNING id",
                (job.id, job.note_id, job.note_title, job.snapshot_text, job.snapshot_hash, job.note_updated_at, job.timezone, job.sensitivity.value, job.project_scope,
                 job.status.value, job.attempts, job.error, job.model, job.reprocess, job.proposal_count, job.inputs_hash, Jsonb([x.model_dump(mode="json") for x in job.sources]), job.created_at, job.started_at, job.finished_at, job.lease_until))
            if await cursor.fetchone():
                return job, True
            # A concurrent request inserted the active job first (the partial unique index): that one is the job.
            row = await (await conn.execute(f"SELECT {_JOB} FROM notepad_jobs WHERE note_id = %s AND status IN ('queued', 'processing')", (job.note_id,))).fetchone()
            return _job(row), False

    async def get_job(self, job_id: str) -> Job | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_JOB} FROM notepad_jobs WHERE id = %s", (job_id,))).fetchone()
        return _job(row) if row else None

    async def latest_job(self, note_id: str) -> Job | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_JOB} FROM notepad_jobs WHERE note_id = %s ORDER BY created_at DESC LIMIT 1", (note_id,))).fetchone()
        return _job(row) if row else None

    async def claim_next(self, now: datetime) -> Job | None:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"UPDATE notepad_jobs SET status = 'processing', attempts = attempts + 1, started_at = %s, lease_until = %s WHERE id = ("
                "SELECT id FROM notepad_jobs WHERE status = 'queued' OR (status = 'processing' AND lease_until <= %s) ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                f") RETURNING {_JOB}", (now, now + timedelta(seconds=LEASE_SECONDS), now))).fetchone()
        return _job(row) if row else None

    async def complete_job(self, job_id: str, proposals: list[Proposal], *, model: str, now: datetime) -> int:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute("SELECT note_id FROM notepad_jobs WHERE id = %s AND status = 'processing' FOR UPDATE", (job_id,))).fetchone()
            if row is None:
                return 0
            added = 0
            for p in proposals:
                if p.source_key and await self._tie_to_existing(conn, p, row[0]):
                    continue  # the same transcript passage was already proposed: one proposal, now also tied to this note
                cursor = await conn.execute(
                    f"INSERT INTO notepad_proposals ({_PROP}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING id",
                    (p.id, p.job_id, p.note_id, p.snapshot_hash, p.kind.value, p.text, p.evidence, p.span_start, p.span_end, Jsonb([x.model_dump(mode="json") for x in p.sources]), p.evidence_from,
                     p.source_key, p.stated_time, p.due_at, Jsonb(p.ambiguity), p.status.value, p.fingerprint, p.model, p.prompt_version, p.sensitivity.value, p.project_scope, None, None, None,
                     p.edited, None, None, p.created_at, None, None))
                if await cursor.fetchone():
                    await conn.execute("INSERT INTO notepad_proposal_notes (proposal_id, note_id, snapshot_hash) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (p.id, row[0], p.snapshot_hash))
                    added += 1
                elif p.source_key:
                    await self._tie_to_existing(conn, p, row[0])  # lost a race to a concurrent job that proposed the same passage
            await conn.execute("UPDATE notepad_jobs SET status = 'succeeded', model = %s, proposal_count = %s, finished_at = %s, lease_until = NULL, error = NULL WHERE id = %s",
                               (model, added, now, job_id))
            return added

    @staticmethod
    async def _tie_to_existing(conn, p: Proposal, note_id: str) -> bool:
        found = await (await conn.execute("SELECT id, status, sensitivity FROM notepad_proposals WHERE source_key = %s FOR UPDATE", (p.source_key,))).fetchone()
        if found is None:
            return False
        await conn.execute("INSERT INTO notepad_proposal_notes (proposal_id, note_id, snapshot_hash) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (found[0], note_id, p.snapshot_hash))
        rank = {"public": 0, "work-private": 1, "sensitive": 2}
        if found[1] == "pending" and rank[p.sensitivity.value] > rank[found[2]]:
            await conn.execute("UPDATE notepad_proposals SET sensitivity = %s WHERE id = %s", (p.sensitivity.value, found[0]))
        return True

    async def fail_job(self, job_id: str, error: str, *, now: datetime) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE notepad_jobs SET status = 'failed', error = %s, finished_at = %s, lease_until = NULL WHERE id = %s AND status = 'processing'", (error, now, job_id))

    async def retry_job(self, job_id: str, *, now: datetime) -> tuple[Job | None, str]:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(f"SELECT {_JOB} FROM notepad_jobs WHERE id = %s FOR UPDATE", (job_id,))).fetchone()
            if row is None:
                return None, "missing"
            job = _job(row)
            if job.status.value != "failed":
                return job, "not_failed"
            active = await (await conn.execute("SELECT 1 FROM notepad_jobs WHERE note_id = %s AND status IN ('queued', 'processing')", (job.note_id,))).fetchone()
            if active:
                return job, "active"
            row = await (await conn.execute(f"UPDATE notepad_jobs SET status = 'queued', error = NULL, finished_at = NULL WHERE id = %s RETURNING {_JOB}", (job_id,))).fetchone()
            return _job(row), "queued"

    async def processed_note_ids(self) -> set[str]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute("SELECT DISTINCT note_id FROM notepad_jobs WHERE status = 'succeeded'")).fetchall()
        return {r[0] for r in rows}

    @staticmethod
    async def _hydrate(conn, proposals: list[Proposal]) -> list[Proposal]:
        if not proposals:
            return proposals
        rows = await (await conn.execute("SELECT proposal_id, note_id, snapshot_hash FROM notepad_proposal_notes WHERE proposal_id = ANY(%s)", ([p.id for p in proposals],))).fetchall()
        by: dict[str, dict[str, str]] = {}
        for pid, nid, h in rows:
            by.setdefault(pid, {})[nid] = h
        return [p.model_copy(update={"associations": by.get(p.id, {})}) for p in proposals]

    async def list_proposals(self, *, note_id: str | None = None, statuses: tuple[ProposalStatus, ...] | None = None) -> list[Proposal]:
        clauses, args = [], []
        if note_id is not None:
            clauses.append("id IN (SELECT proposal_id FROM notepad_proposal_notes WHERE note_id = %s)")
            args.append(note_id)
        if statuses is not None:
            clauses.append("status = ANY(%s)")
            args.append([s.value for s in statuses])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_PROP} FROM notepad_proposals {where} ORDER BY created_at, span_start", args)).fetchall()
            return await self._hydrate(conn, [_proposal(r) for r in rows])

    async def get_proposal(self, proposal_id: str) -> Proposal | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_PROP} FROM notepad_proposals WHERE id = %s", (proposal_id,))).fetchone()
            return (await self._hydrate(conn, [_proposal(row)]))[0] if row else None

    async def claim_accept(self, proposal_id: str, *, kind: Kind, text: str, due_at: datetime | None, sensitivity: Privacy, edited: bool, now: datetime) -> Claim:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                "UPDATE notepad_proposals SET status = 'accepting', final_kind = %s, final_text = %s, final_due_at = %s, sensitivity = %s, edited = %s, accepting_at = %s "
                f"WHERE id = %s AND status = 'pending' RETURNING {_PROP}", (kind.value, text, due_at, sensitivity.value, edited, now, proposal_id))).fetchone()
            if row:
                return Claim("claimed", _proposal(row))
            current = await (await conn.execute(f"SELECT {_PROP} FROM notepad_proposals WHERE id = %s FOR UPDATE", (proposal_id,))).fetchone()
            if current is None:
                return Claim("missing")
            p = _proposal(current)
            if p.status is ProposalStatus.ACCEPTED:
                return Claim("done", p)
            if p.status is ProposalStatus.ACCEPTING:
                if p.accepting_at is not None and (now - p.accepting_at).total_seconds() < ACCEPTING_STALE_SECONDS:
                    return Claim("in_progress", p)
                row = await (await conn.execute(f"UPDATE notepad_proposals SET accepting_at = %s WHERE id = %s AND status = 'accepting' RETURNING {_PROP}", (now, proposal_id))).fetchone()
                return Claim("claimed", _proposal(row))
            return Claim("closed", p)

    async def finish_accept(self, proposal_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Proposal | None:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                "UPDATE notepad_proposals SET status = 'accepted', record_kind = %s, record_id = %s, decided_at = %s "
                f"WHERE id = %s AND status = 'accepting' RETURNING {_PROP}", (record_kind, record_id, now, proposal_id))).fetchone()
            if row:
                return _proposal(row)
            row = await (await conn.execute(f"SELECT {_PROP} FROM notepad_proposals WHERE id = %s AND status = 'accepted'", (proposal_id,))).fetchone()
        return _proposal(row) if row else None

    async def dismiss(self, proposal_id: str, *, now: datetime) -> Decision:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"UPDATE notepad_proposals SET status = 'dismissed', decided_at = %s WHERE id = %s AND status = 'pending' RETURNING {_PROP}", (now, proposal_id))).fetchone()
            if row:
                return Decision("done", _proposal(row))
            current = await (await conn.execute(f"SELECT {_PROP} FROM notepad_proposals WHERE id = %s", (proposal_id,))).fetchone()
        if current is None:
            return Decision("missing")
        p = _proposal(current)
        return Decision("already" if p.status is ProposalStatus.DISMISSED else "closed", p)

    async def close_for_note(self, note_id: str, *, now: datetime) -> int:
        """The note is gone: untie it from its proposals, and dismiss each pending one that no remaining note still backs."""
        async with self._pool.connection() as conn, conn.transaction():
            gone = [r[0] for r in await (await conn.execute("DELETE FROM notepad_proposal_notes WHERE note_id = %s RETURNING proposal_id", (note_id,))).fetchall()]
            if not gone:
                return 0
            cursor = await conn.execute(
                "UPDATE notepad_proposals SET status = 'dismissed', decided_at = %s WHERE id = ANY(%s) AND status = 'pending' "
                "AND NOT EXISTS (SELECT 1 FROM notepad_proposal_notes n WHERE n.proposal_id = notepad_proposals.id)", (now, gone))
            return cursor.rowcount

    async def stale_accepting(self, now: datetime) -> list[str]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute("SELECT id FROM notepad_proposals WHERE status = 'accepting' AND (accepting_at IS NULL OR accepting_at <= %s)",
                                             (now - timedelta(seconds=ACCEPTING_STALE_SECONDS),))).fetchall()
        return [r[0] for r in rows]

    async def add_provenance(self, provenance: Provenance) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO notepad_provenance (record_kind, record_id, note_id, proposal_id, snapshot_hash, created_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (provenance.record_kind, provenance.record_id, provenance.note_id, provenance.proposal_id, provenance.snapshot_hash, provenance.created_at))

    async def suggest_link(self, link: MeetingLink) -> MeetingLink:
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO note_meeting_links ({_LINK}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (note_id, meeting_id) DO NOTHING",
                (link.id, link.note_id, link.meeting_id, link.source, link.state, link.overlap_seconds, link.title_match, link.created_at, link.updated_at, link.decided_at))
            row = await (await conn.execute(f"SELECT {_LINK} FROM note_meeting_links WHERE note_id = %s AND meeting_id = %s", (link.note_id, link.meeting_id))).fetchone()
        return _link(row)

    async def set_link(self, note_id: str, meeting_id: str, *, state: str, now: datetime) -> MeetingLink:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"INSERT INTO note_meeting_links ({_LINK}) VALUES (%s,%s,%s,'explicit',%s,NULL,FALSE,%s,%s,%s) "
                "ON CONFLICT (note_id, meeting_id) DO UPDATE SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at, decided_at = EXCLUDED.decided_at "
                f"RETURNING {_LINK}", (str(uuid.uuid4()), note_id, meeting_id, state, now, now, now))).fetchone()
        return _link(row)

    async def list_links(self, *, note_id: str | None = None, meeting_id: str | None = None, states: tuple[str, ...] | None = None) -> list[MeetingLink]:
        clauses, args = [], []
        for column, value in (("note_id", note_id), ("meeting_id", meeting_id)):
            if value is not None:
                clauses.append(f"{column} = %s")
                args.append(value)
        if states is not None:
            clauses.append("state = ANY(%s)")
            args.append(list(states))
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(f"SELECT {_LINK} FROM note_meeting_links {where} ORDER BY created_at, meeting_id", args)).fetchall()
        return [_link(r) for r in rows]

    async def drop_links(self, *, note_id: str | None = None, meeting_id: str | None = None) -> int:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("DELETE FROM note_meeting_links WHERE (%s::text IS NOT NULL AND note_id = %s) OR (%s::text IS NOT NULL AND meeting_id = %s)",
                                        (note_id, note_id, meeting_id, meeting_id))
            return cursor.rowcount

    async def list_provenance(self, record_ids: list[str]) -> list[Provenance]:
        """Read-only: the provenance rows of these task or reminder ids (the Brain's `derived_from` edges)."""
        if not record_ids:
            return []
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT record_kind, record_id, note_id, proposal_id, snapshot_hash, created_at FROM notepad_provenance WHERE record_id = ANY(%s) ORDER BY created_at, proposal_id",
                (list(record_ids),))).fetchall()
        keys = ("record_kind", "record_id", "note_id", "proposal_id", "snapshot_hash", "created_at")
        return [Provenance(**dict(zip(keys, r, strict=True))) for r in rows]

    async def get_provenance(self, record_kind: str, record_id: str) -> Provenance | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT record_kind, record_id, note_id, proposal_id, snapshot_hash, created_at FROM notepad_provenance WHERE record_kind = %s AND record_id = %s", (record_kind, record_id))).fetchone()
        return Provenance(**dict(zip(("record_kind", "record_id", "note_id", "proposal_id", "snapshot_hash", "created_at"), row, strict=True))) if row else None
