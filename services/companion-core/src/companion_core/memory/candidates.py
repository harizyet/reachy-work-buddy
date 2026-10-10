"""Memory candidates (Phase 44F; docs/phase-44f-implementation-proposal.md): the store.

A candidate is a *proposal* made from the owner's own words. It is not memory: it lives in its own tables, no trigger or foreign key connects it to `memories` or the knowledge index, and
nothing but the review code and the retention job reads it (it is absent from recall, retrieval, context bundles and prompts by construction). Only an explicit owner accept creates a memory,
through the existing `add_memory`, and the store guarantees a candidate becomes at most one memory.

States: pending -> accepting -> accepted / edited-accepted (the memory exists), pending -> rejected / suppressed, pending -> deleted (expiry, forget-conversation). Candidate text exists only while a
candidate is pending or accepting (a database CHECK enforces it). Digests are keyed HMACs computed by the caller; the store never sees a plain hash.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from shared.database import check_schema, close_pool, open_pool
from shared.models.memory import MemoryType
from shared.models.response import Privacy

PENDING_DAYS = 14
DECIDED_METADATA_DAYS = 30
COUNTER_DAYS = 365
HOURLY_CAP = 5
DAILY_CAP = 20
ACCEPTING_STALE_SECONDS = 120
MAX_TEXT = 400
MAX_LIST = 100


class CandidateStatus(StrEnum):
    PENDING = "pending"
    ACCEPTING = "accepting"
    ACCEPTED = "accepted"
    EDITED_ACCEPTED = "edited-accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPPRESSED = "suppressed"


OPEN = (CandidateStatus.PENDING, CandidateStatus.ACCEPTING)
ACCEPTED = (CandidateStatus.ACCEPTED, CandidateStatus.EDITED_ACCEPTED)


class Candidate(BaseModel):
    id: str
    text: str | None
    rule_id: str
    rule_version: int
    conversation_id: str | None = None
    session_id: str | None = None
    turn_index: int | None = None
    channel: str
    proposed_type: MemoryType
    proposed_scope: str | None = None
    sensitivity: Privacy
    status: CandidateStatus
    digest: str
    digest_key_id: str
    memory_id: str | None = None
    edited: bool = False
    expires_memory_at: datetime | None = None
    created_at: datetime
    expires_at: datetime
    accepting_at: datetime | None = None
    decided_at: datetime | None = None

    def view(self) -> dict:
        """What the review surface may show: no digest, no key id."""
        return self.model_dump(mode="json", exclude={"digest", "digest_key_id"})


def new_candidate(*, text: str, rule_id: str, rule_version: int, conversation_id: str | None, session_id: str | None, turn_index: int | None, channel: str,
                  proposed_type: MemoryType, proposed_scope: str | None, sensitivity: Privacy, digest: str, digest_key_id: str, now: datetime) -> Candidate:
    return Candidate(id=str(uuid.uuid4()), text=text, rule_id=rule_id, rule_version=rule_version, conversation_id=conversation_id, session_id=session_id, turn_index=turn_index,
                     channel=channel, proposed_type=proposed_type, proposed_scope=proposed_scope, sensitivity=sensitivity, status=CandidateStatus.PENDING, digest=digest,
                     digest_key_id=digest_key_id, created_at=now, expires_at=now + timedelta(days=PENDING_DAYS))


@dataclass(frozen=True)
class Claim:
    outcome: str  # claimed | in_progress | done | closed | expired | missing
    candidate: Candidate | None = None


@dataclass(frozen=True)
class Decision:
    outcome: str  # done | already | closed | missing
    candidate: Candidate | None = None


def hour_of(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


class CandidateStore(Protocol):
    async def create(self, candidate: Candidate, lookup: list[tuple[str, str]], *, hourly_cap: int = HOURLY_CAP, daily_cap: int = DAILY_CAP) -> tuple[Candidate | None, str]: ...
    async def get(self, candidate_id: str) -> Candidate | None: ...
    async def list_pending(self, now: datetime, limit: int = MAX_LIST) -> list[Candidate]: ...
    async def claim_accept(self, candidate_id: str, *, text: str, type: MemoryType, scope: str | None, sensitivity: Privacy, memory_expires_at: datetime | None, edited: bool,
                           now: datetime, stale_after: float = ACCEPTING_STALE_SECONDS) -> Claim: ...
    async def finish_accept(self, candidate_id: str, memory_id: str, *, now: datetime) -> Candidate | None: ...
    async def reject(self, candidate_id: str, *, suppress: bool, now: datetime) -> Decision: ...
    async def forget_conversation(self, conversation_id: str, now: datetime) -> int: ...
    async def stale_accepting(self, now: datetime, older_than: float = ACCEPTING_STALE_SECONDS) -> list[str]: ...
    async def accepted_links(self) -> list[tuple[str, str]]: ...
    async def clear_provenance(self, candidate_id: str) -> None: ...
    async def delete(self, candidate_id: str) -> None: ...
    async def maintain(self, now: datetime) -> dict[str, int]: ...
    async def counters(self, since: datetime) -> dict[str, int]: ...
    async def close(self) -> None: ...


def _decided(c: Candidate, status: CandidateStatus, now: datetime) -> Candidate:
    return c.model_copy(update={"status": status, "text": None, "decided_at": now})


class InMemoryCandidateStore:
    """The in-memory twin: the same states, caps and guarantees, for tests and for a deployment without a database."""

    def __init__(self) -> None:
        self._rows: dict[str, Candidate] = {}
        self._suppressed: set[tuple[str, str]] = set()
        self._counters: dict[tuple[datetime, str], int] = {}

    def _bump(self, kind: str, now: datetime, n: int = 1) -> None:
        key = (hour_of(now), kind)
        self._counters[key] = self._counters.get(key, 0) + n

    async def create(self, candidate: Candidate, lookup: list[tuple[str, str]], *, hourly_cap: int = HOURLY_CAP, daily_cap: int = DAILY_CAP) -> tuple[Candidate | None, str]:
        now = candidate.created_at
        if any(key in self._suppressed for key in lookup):
            return None, "suppressed"
        if any(c.status in OPEN and (c.digest_key_id, c.digest) in lookup for c in self._rows.values()):
            return None, "duplicate"
        if self._counters.get((hour_of(now), "proposed"), 0) >= hourly_cap:
            return None, "hourly_cap"
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if sum(n for (h, k), n in self._counters.items() if k == "proposed" and h >= day) >= daily_cap:
            return None, "daily_cap"
        self._rows[candidate.id] = candidate
        self._bump("proposed", now)
        return candidate, "created"

    async def get(self, candidate_id: str) -> Candidate | None:
        return self._rows.get(candidate_id)

    async def list_pending(self, now: datetime, limit: int = MAX_LIST) -> list[Candidate]:
        rows = [c for c in self._rows.values() if c.status is CandidateStatus.PENDING and c.expires_at > now]
        return sorted(rows, key=lambda c: c.created_at, reverse=True)[:limit]

    async def claim_accept(self, candidate_id: str, *, text: str, type: MemoryType, scope: str | None, sensitivity: Privacy, memory_expires_at: datetime | None, edited: bool,
                           now: datetime, stale_after: float = ACCEPTING_STALE_SECONDS) -> Claim:
        c = self._rows.get(candidate_id)
        if c is None:
            return Claim("missing")
        if c.status in ACCEPTED:
            return Claim("done", c)
        if c.status is CandidateStatus.ACCEPTING:
            if c.accepting_at is not None and (now - c.accepting_at).total_seconds() < stale_after:
                return Claim("in_progress", c)
            self._rows[candidate_id] = c = c.model_copy(update={"accepting_at": now})  # reclaimed: the stored final values are used, not the new request's
            return Claim("claimed", c)
        if c.status is not CandidateStatus.PENDING:
            return Claim("closed", c)
        if c.expires_at <= now:
            return Claim("expired", c)
        self._rows[candidate_id] = c = c.model_copy(update={"status": CandidateStatus.ACCEPTING, "text": text, "proposed_type": type, "proposed_scope": scope, "sensitivity": sensitivity,
                                                            "expires_memory_at": memory_expires_at, "accepting_at": now, "edited": edited})
        return Claim("claimed", c)

    async def finish_accept(self, candidate_id: str, memory_id: str, *, now: datetime) -> Candidate | None:
        c = self._rows.get(candidate_id)
        if c is None or c.status is not CandidateStatus.ACCEPTING:
            return self._rows.get(candidate_id) if c is not None and c.status in ACCEPTED else None
        edited = c.edited
        status = CandidateStatus.EDITED_ACCEPTED if edited else CandidateStatus.ACCEPTED
        self._rows[candidate_id] = done = _decided(c, status, now).model_copy(update={"memory_id": memory_id})
        self._bump("edited_accepted" if edited else "accepted", now)
        return done

    async def reject(self, candidate_id: str, *, suppress: bool, now: datetime) -> Decision:
        c = self._rows.get(candidate_id)
        if c is None:
            return Decision("missing")
        if c.status in (CandidateStatus.REJECTED, CandidateStatus.SUPPRESSED):
            return Decision("already", c)
        if c.status is not CandidateStatus.PENDING:
            return Decision("closed", c)
        if suppress:
            self._suppressed.add((c.digest_key_id, c.digest))
        self._rows[candidate_id] = done = _decided(c, CandidateStatus.SUPPRESSED if suppress else CandidateStatus.REJECTED, now)
        self._bump("suppressed" if suppress else "rejected", now)
        return Decision("done", done)

    async def forget_conversation(self, conversation_id: str, now: datetime) -> int:
        ids = [c.id for c in self._rows.values() if c.conversation_id == conversation_id and c.status is CandidateStatus.PENDING]
        for i in ids:
            del self._rows[i]
        if ids:
            self._bump("forgotten", now, len(ids))
        return len(ids)

    async def stale_accepting(self, now: datetime, older_than: float = ACCEPTING_STALE_SECONDS) -> list[str]:
        return [c.id for c in self._rows.values() if c.status is CandidateStatus.ACCEPTING and c.accepting_at is not None and (now - c.accepting_at).total_seconds() >= older_than]

    async def accepted_links(self) -> list[tuple[str, str]]:
        return [(c.id, c.memory_id) for c in self._rows.values() if c.status in ACCEPTED and c.memory_id]

    async def clear_provenance(self, candidate_id: str) -> None:
        c = self._rows.get(candidate_id)
        if c is not None:
            self._rows[candidate_id] = c.model_copy(update={"conversation_id": None, "session_id": None, "turn_index": None})

    async def delete(self, candidate_id: str) -> None:
        self._rows.pop(candidate_id, None)

    async def maintain(self, now: datetime) -> dict[str, int]:
        expired = [c.id for c in self._rows.values() if c.status is CandidateStatus.PENDING and c.expires_at <= now]
        old = [c.id for c in self._rows.values() if c.status in (CandidateStatus.REJECTED, CandidateStatus.SUPPRESSED) and c.decided_at and c.decided_at <= now - timedelta(days=DECIDED_METADATA_DAYS)]
        for i in [*expired, *old]:
            del self._rows[i]
        if expired:
            self._bump("expired", now, len(expired))
        stale = [key for key in self._counters if key[0] < now - timedelta(days=COUNTER_DAYS)]
        for key in stale:
            del self._counters[key]
        return {"expired": len(expired), "decided_metadata_purged": len(old), "counters_purged": len(stale)}

    async def counters(self, since: datetime) -> dict[str, int]:
        out: dict[str, int] = {}
        for (h, kind), n in self._counters.items():
            if h >= since:
                out[kind] = out.get(kind, 0) + n
        return out

    async def close(self) -> None:
        return None


_COLUMNS = ("id, text, rule_id, rule_version, conversation_id, session_id, turn_index, channel, proposed_type, proposed_scope, sensitivity, status, digest, digest_key_id, memory_id, "
            "edited, expires_memory_at, created_at, expires_at, accepting_at, decided_at")


def _from_row(row: tuple) -> Candidate:
    return Candidate(id=row[0], text=row[1], rule_id=row[2], rule_version=row[3], conversation_id=row[4], session_id=row[5], turn_index=row[6], channel=row[7],
                     proposed_type=MemoryType(row[8]), proposed_scope=row[9], sensitivity=Privacy(row[10]), status=CandidateStatus(row[11]), digest=row[12], digest_key_id=row[13],
                     memory_id=row[14], edited=row[15], expires_memory_at=row[16], created_at=row[17], expires_at=row[18], accepting_at=row[19], decided_at=row[20])


class PostgresCandidateStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, source) -> PostgresCandidateStore:
        pool = await open_pool(source)
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await close_pool(self._pool)

    @staticmethod
    async def _bump(conn, kind: str, now: datetime, n: int = 1) -> None:
        await conn.execute("INSERT INTO memory_candidate_counters (hour, kind, n) VALUES (%s, %s, %s) ON CONFLICT (hour, kind) DO UPDATE SET n = memory_candidate_counters.n + EXCLUDED.n",
                           (hour_of(now), kind, n))

    async def create(self, candidate: Candidate, lookup: list[tuple[str, str]], *, hourly_cap: int = HOURLY_CAP, daily_cap: int = DAILY_CAP) -> tuple[Candidate | None, str]:
        now = candidate.created_at
        async with self._pool.connection() as conn, conn.transaction():
            # One capture worker proposes one candidate at a time and the counter upsert is atomic, so no advisory lock is needed (and none is allowed behind transaction pooling).
            for key_id, digest in lookup:
                if (await (await conn.execute("SELECT 1 FROM memory_candidate_suppressions WHERE digest_key_id = %s AND digest = %s", (key_id, digest))).fetchone()):
                    return None, "suppressed"
                if (await (await conn.execute("SELECT 1 FROM memory_candidates WHERE digest_key_id = %s AND digest = %s AND status IN ('pending', 'accepting')", (key_id, digest))).fetchone()):
                    return None, "duplicate"
            hourly = (await (await conn.execute("SELECT coalesce(sum(n), 0) FROM memory_candidate_counters WHERE kind = 'proposed' AND hour = %s", (hour_of(now),))).fetchone())[0]
            if hourly >= hourly_cap:
                return None, "hourly_cap"
            day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            daily = (await (await conn.execute("SELECT coalesce(sum(n), 0) FROM memory_candidate_counters WHERE kind = 'proposed' AND hour >= %s", (day,))).fetchone())[0]
            if daily >= daily_cap:
                return None, "daily_cap"
            await conn.execute(
                f"INSERT INTO memory_candidates ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (candidate.id, candidate.text, candidate.rule_id, candidate.rule_version, candidate.conversation_id, candidate.session_id, candidate.turn_index, candidate.channel,
                 candidate.proposed_type.value, candidate.proposed_scope, candidate.sensitivity.value, candidate.status.value, candidate.digest, candidate.digest_key_id,
                 candidate.memory_id, candidate.edited, candidate.expires_memory_at, candidate.created_at, candidate.expires_at, candidate.accepting_at, candidate.decided_at))
            await self._bump(conn, "proposed", now)
        return candidate, "created"

    async def get(self, candidate_id: str) -> Candidate | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(f"SELECT {_COLUMNS} FROM memory_candidates WHERE id = %s", (candidate_id,))).fetchone()
        return _from_row(row) if row else None

    async def list_pending(self, now: datetime, limit: int = MAX_LIST) -> list[Candidate]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM memory_candidates WHERE status = 'pending' AND expires_at > %s ORDER BY created_at DESC LIMIT %s", (now, limit))
            return [_from_row(r) for r in await cur.fetchall()]

    async def claim_accept(self, candidate_id: str, *, text: str, type: MemoryType, scope: str | None, sensitivity: Privacy, memory_expires_at: datetime | None, edited: bool,
                           now: datetime, stale_after: float = ACCEPTING_STALE_SECONDS) -> Claim:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"UPDATE memory_candidates SET status = 'accepting', text = %s, proposed_type = %s, proposed_scope = %s, sensitivity = %s, expires_memory_at = %s, accepting_at = %s, edited = %s "
                f"WHERE id = %s AND status = 'pending' AND expires_at > %s RETURNING {_COLUMNS}",
                (text, type.value, scope, sensitivity.value, memory_expires_at, now, edited, candidate_id, now))).fetchone()
            if row:
                return Claim("claimed", _from_row(row))
            current = await (await conn.execute(f"SELECT {_COLUMNS} FROM memory_candidates WHERE id = %s FOR UPDATE", (candidate_id,))).fetchone()
            if current is None:
                return Claim("missing")
            c = _from_row(current)
            if c.status in ACCEPTED:
                return Claim("done", c)
            if c.status is CandidateStatus.ACCEPTING:
                if c.accepting_at is not None and (now - c.accepting_at).total_seconds() < stale_after:
                    return Claim("in_progress", c)
                row = await (await conn.execute(f"UPDATE memory_candidates SET accepting_at = %s WHERE id = %s AND status = 'accepting' RETURNING {_COLUMNS}", (now, candidate_id))).fetchone()
                return Claim("claimed", _from_row(row))
            if c.status is CandidateStatus.PENDING:
                return Claim("expired", c)
            return Claim("closed", c)

    async def finish_accept(self, candidate_id: str, memory_id: str, *, now: datetime) -> Candidate | None:
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"UPDATE memory_candidates SET status = CASE WHEN edited THEN 'edited-accepted' ELSE 'accepted' END, text = NULL, memory_id = %s, decided_at = %s "
                f"WHERE id = %s AND status = 'accepting' RETURNING {_COLUMNS}", (memory_id, now, candidate_id))).fetchone()
            if row:
                done = _from_row(row)
                await self._bump(conn, "edited_accepted" if done.edited else "accepted", now)
                return done
            row = await (await conn.execute(f"SELECT {_COLUMNS} FROM memory_candidates WHERE id = %s AND status IN ('accepted', 'edited-accepted')", (candidate_id,))).fetchone()
        return _from_row(row) if row else None

    async def reject(self, candidate_id: str, *, suppress: bool, now: datetime) -> Decision:
        status = CandidateStatus.SUPPRESSED if suppress else CandidateStatus.REJECTED
        async with self._pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                f"UPDATE memory_candidates SET status = %s, text = NULL, decided_at = %s WHERE id = %s AND status = 'pending' RETURNING {_COLUMNS}", (status.value, now, candidate_id))).fetchone()
            if row:
                c = _from_row(row)
                if suppress:
                    await conn.execute("INSERT INTO memory_candidate_suppressions (digest_key_id, digest, rule_id, created_at) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                                       (c.digest_key_id, c.digest, c.rule_id, now))
                await self._bump(conn, status.value, now)
                return Decision("done", c)
            current = await (await conn.execute(f"SELECT {_COLUMNS} FROM memory_candidates WHERE id = %s", (candidate_id,))).fetchone()
        if current is None:
            return Decision("missing")
        c = _from_row(current)
        return Decision("already" if c.status in (CandidateStatus.REJECTED, CandidateStatus.SUPPRESSED) else "closed", c)

    async def forget_conversation(self, conversation_id: str, now: datetime) -> int:
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute("DELETE FROM memory_candidates WHERE conversation_id = %s AND status = 'pending'", (conversation_id,))
            n = cur.rowcount
            if n:
                await self._bump(conn, "forgotten", now, n)
        return n

    async def stale_accepting(self, now: datetime, older_than: float = ACCEPTING_STALE_SECONDS) -> list[str]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT id FROM memory_candidates WHERE status = 'accepting' AND accepting_at <= %s", (now - timedelta(seconds=older_than),))
            return [r[0] for r in await cur.fetchall()]

    async def accepted_links(self) -> list[tuple[str, str]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT id, memory_id FROM memory_candidates WHERE status IN ('accepted', 'edited-accepted')")
            return [(r[0], r[1]) for r in await cur.fetchall()]

    async def clear_provenance(self, candidate_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("UPDATE memory_candidates SET conversation_id = NULL, session_id = NULL, turn_index = NULL WHERE id = %s", (candidate_id,))

    async def delete(self, candidate_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM memory_candidates WHERE id = %s", (candidate_id,))

    async def maintain(self, now: datetime) -> dict[str, int]:
        async with self._pool.connection() as conn, conn.transaction():
            expired = (await conn.execute("DELETE FROM memory_candidates WHERE status = 'pending' AND expires_at <= %s", (now,))).rowcount
            old = (await conn.execute("DELETE FROM memory_candidates WHERE status IN ('rejected', 'suppressed') AND decided_at <= %s", (now - timedelta(days=DECIDED_METADATA_DAYS),))).rowcount
            if expired:
                await self._bump(conn, "expired", now, expired)
            stale = (await conn.execute("DELETE FROM memory_candidate_counters WHERE hour < %s", (now - timedelta(days=COUNTER_DAYS),))).rowcount
        return {"expired": expired, "decided_metadata_purged": old, "counters_purged": stale}

    async def counters(self, since: datetime) -> dict[str, int]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT kind, sum(n) FROM memory_candidate_counters WHERE hour >= %s GROUP BY kind", (since,))
            return {r[0]: int(r[1]) for r in await cur.fetchall()}


def utcnow() -> datetime:
    return datetime.now(UTC)
