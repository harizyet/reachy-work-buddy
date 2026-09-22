"""Work memory storage — real implementation of `MemoryRecord`
(shared/models/memory.py), which existed as a forward-looking data contract
since Phase 0 and sat unused until this phase actually built against it.

Expiry (docs/plan.md's Phase 12 deliverable: "...with provenance,
sensitivity and expiry") is enforced at read time: `recall`/`list_memories`/
`get` simply never return a record whose `expires_at` has passed. There's
no background cleanup job — that's the same scope discipline used for
calendar reminders (Phase 10) and is not required by the exit criterion; an
expired record just becomes permanently unreachable through this store's
own API, whether or not it's still physically in the table.

`recall` (not `list_memories`) is genuinely how "Stored work fact can be
recalled later without transcript dumping" (the exit criterion) is
satisfied: it's a targeted content search against durable storage,
completely separate from `conversation.py`'s per-session transcript — the
reply built from it never touches raw conversation history.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from shared.models.memory import MemoryRecord, MemoryType
from shared.models.response import Privacy


class MemoryStore(Protocol):
    async def add_memory(
        self,
        *,
        content: str,
        source: str,
        type: MemoryType = MemoryType.WORKING,
        project_scope: str | None = None,
        confidence: float = 1.0,
        sensitivity: Privacy = Privacy.WORK_PRIVATE,
        expires_at: datetime | None = None,
    ) -> MemoryRecord: ...

    async def recall(self, query: str, *, type: MemoryType | None = None) -> list[MemoryRecord]: ...
    async def list_memories(self, type: MemoryType | None = None) -> list[MemoryRecord]: ...
    async def get(self, memory_id: str) -> MemoryRecord | None: ...
    async def forget(self, memory_id: str) -> bool: ...


def _not_expired(record: MemoryRecord, now: datetime) -> bool:
    return record.expires_at is None or record.expires_at > now


class InMemoryMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    async def add_memory(
        self,
        *,
        content: str,
        source: str,
        type: MemoryType = MemoryType.WORKING,
        project_scope: str | None = None,
        confidence: float = 1.0,
        sensitivity: Privacy = Privacy.WORK_PRIVATE,
        expires_at: datetime | None = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            type=type,
            content=content,
            source=source,
            project_scope=project_scope,
            confidence=confidence,
            sensitivity=sensitivity,
            expires_at=expires_at,
        )
        self._records[record.id] = record
        return record

    async def recall(self, query: str, *, type: MemoryType | None = None) -> list[MemoryRecord]:
        now = datetime.now(UTC)
        lowered = query.lower()
        matches = [
            r
            for r in self._records.values()
            if _not_expired(r, now) and lowered in r.content.lower() and (type is None or r.type == type)
        ]
        matches.sort(key=lambda r: r.created_at)
        for record in matches:
            record.last_accessed = now
        return matches

    async def list_memories(self, type: MemoryType | None = None) -> list[MemoryRecord]:
        now = datetime.now(UTC)
        results = [r for r in self._records.values() if _not_expired(r, now) and (type is None or r.type == type)]
        return sorted(results, key=lambda r: r.created_at)

    async def get(self, memory_id: str) -> MemoryRecord | None:
        record = self._records.get(memory_id)
        if record is None or not _not_expired(record, datetime.now(UTC)):
            return None
        return record

    async def forget(self, memory_id: str) -> bool:
        return self._records.pop(memory_id, None) is not None
