"""Phase 31 stores: runs and items. The in-memory twin has the same states and guarantees as the PostgreSQL store (postgres_store.py); both follow Phase 49's store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from companion_core.meeting_analysis.models import (
    ACCEPTING_STALE_SECONDS,
    ACTIVE_RUNS,
    LEASE_SECONDS,
    Item,
    ItemKind,
    ItemStatus,
    Run,
    RunStatus,
    same_finding,
)
from shared.models.response import Privacy

OPEN_ITEMS = (ItemStatus.PENDING, ItemStatus.ACCEPTING)


@dataclass(frozen=True)
class Claim:
    outcome: str  # claimed | in_progress | done | closed | missing
    item: Item | None = None


@dataclass(frozen=True)
class Decision:
    outcome: str  # done | already | closed | missing
    item: Item | None = None


class MeetingAnalysisStore(Protocol):
    async def enqueue(self, run: Run, *, force: bool) -> tuple[Run, bool]: ...
    async def get_run(self, run_id: str) -> Run | None: ...
    async def latest_run(self, meeting_id: str) -> Run | None: ...
    async def claim_next(self, now: datetime) -> Run | None: ...
    async def complete_run(self, run_id: str, items: list[Item], *, model: str, rejected: dict[str, int], now: datetime) -> int: ...
    async def fail_run(self, run_id: str, error: str, *, now: datetime) -> None: ...
    async def retry_run(self, run_id: str, *, now: datetime) -> tuple[Run | None, str]: ...
    async def list_items(self, *, meeting_id: str | None = None, statuses: tuple[ItemStatus, ...] | None = None) -> list[Item]: ...
    async def get_item(self, item_id: str) -> Item | None: ...
    async def item_for_record(self, record_id: str) -> Item | None: ...
    async def claim_accept(self, item_id: str, *, text: str, sensitivity: Privacy, edited: bool, now: datetime) -> Claim: ...
    async def finish_accept(self, item_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Item | None: ...
    async def dismiss(self, item_id: str, *, now: datetime) -> Decision: ...
    async def stale_accepting(self, now: datetime) -> list[str]: ...
    async def drop_meeting(self, meeting_id: str) -> int: ...
    async def close(self) -> None: ...


def retrievable(item: Item) -> bool:
    """What the knowledge index may show: decisions and open questions the owner has not dismissed, and ACCEPTED actions. A pending action is an unreviewed candidate and is never offered as a fact."""
    if item.status is ItemStatus.NOTED:
        return True
    return item.kind is ItemKind.ACTION and item.status is ItemStatus.ACCEPTED


class InMemoryMeetingAnalysisStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._items: dict[str, Item] = {}

    async def enqueue(self, run: Run, *, force: bool) -> tuple[Run, bool]:
        for existing in self._runs.values():
            if existing.meeting_id == run.meeting_id and existing.status in ACTIVE_RUNS:
                return existing, False
        if not force:
            for existing in self._runs.values():
                if existing.meeting_id == run.meeting_id and existing.inputs_hash == run.inputs_hash and existing.status is RunStatus.SUCCEEDED:
                    return existing, False
        self._runs[run.id] = run
        return run, True

    async def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    async def latest_run(self, meeting_id: str) -> Run | None:
        runs = [r for r in self._runs.values() if r.meeting_id == meeting_id]
        return max(reversed(runs), key=lambda r: r.created_at, default=None)

    async def claim_next(self, now: datetime) -> Run | None:
        ready = [r for r in self._runs.values()
                 if r.status is RunStatus.QUEUED or (r.status is RunStatus.PROCESSING and r.lease_until is not None and r.lease_until <= now)]
        if not ready:
            return None
        run = min(ready, key=lambda r: r.created_at)
        self._runs[run.id] = claimed = run.model_copy(update={
            "status": RunStatus.PROCESSING, "attempts": run.attempts + 1, "started_at": now, "lease_until": now + timedelta(seconds=LEASE_SECONDS)})
        return claimed

    async def complete_run(self, run_id: str, items: list[Item], *, model: str, rejected: dict[str, int], now: datetime) -> int:
        run = self._runs.get(run_id)
        if run is None or run.status is not RunStatus.PROCESSING:
            return 0
        held = [i for i in self._items.values() if i.meeting_id == run.meeting_id]
        added = 0
        for item in items:
            match = next((i for i in held if i.fingerprint == item.fingerprint or same_finding(i, item)), None)
            if match is not None:
                # Already extracted, accepted or dismissed: re-analysis never brings it back, however the model words or extends the quote this time. An item the owner has not decided is
                # refreshed from the new run, so its evidence matches the transcript as it reads now; a decided one is left exactly as it was.
                if match.status in (ItemStatus.PENDING, ItemStatus.NOTED):
                    self._items[match.id] = match.model_copy(update={
                        "run_id": item.run_id, "transcript_hash": item.transcript_hash, "text": item.text, "evidence": item.evidence, "assignee": item.assignee, "stated_time": item.stated_time,
                        "due_at": item.due_at, "ambiguity": item.ambiguity, "support": item.support, "model": item.model, "prompt_version": item.prompt_version})
                continue
            held.append(item)
            self._items[item.id] = item
            added += 1
        self._runs[run_id] = run.model_copy(update={"status": RunStatus.SUCCEEDED, "model": model, "item_count": added, "rejected": rejected, "finished_at": now, "lease_until": None, "error": None})
        return added

    async def fail_run(self, run_id: str, error: str, *, now: datetime) -> None:
        run = self._runs.get(run_id)
        if run is not None and run.status is RunStatus.PROCESSING:
            self._runs[run_id] = run.model_copy(update={"status": RunStatus.FAILED, "error": error, "finished_at": now, "lease_until": None})

    async def retry_run(self, run_id: str, *, now: datetime) -> tuple[Run | None, str]:
        run = self._runs.get(run_id)
        if run is None:
            return None, "missing"
        if run.status is not RunStatus.FAILED:
            return run, "not_failed"
        if any(r.meeting_id == run.meeting_id and r.status in ACTIVE_RUNS for r in self._runs.values()):
            return run, "active"
        self._runs[run_id] = queued = run.model_copy(update={"status": RunStatus.QUEUED, "error": None, "finished_at": None})
        return queued, "queued"

    async def list_items(self, *, meeting_id: str | None = None, statuses: tuple[ItemStatus, ...] | None = None) -> list[Item]:
        rows = [i for i in self._items.values() if (meeting_id is None or i.meeting_id == meeting_id) and (statuses is None or i.status in statuses)]
        return sorted(rows, key=lambda i: (i.evidence[0].start, i.created_at, i.kind.value))

    async def get_item(self, item_id: str) -> Item | None:
        return self._items.get(item_id)

    async def item_for_record(self, record_id: str) -> Item | None:
        return next((i for i in self._items.values() if i.record_id == record_id), None)

    async def claim_accept(self, item_id: str, *, text: str, sensitivity: Privacy, edited: bool, now: datetime) -> Claim:
        i = self._items.get(item_id)
        if i is None:
            return Claim("missing")
        if i.status is ItemStatus.ACCEPTED:
            return Claim("done", i)
        if i.status is ItemStatus.ACCEPTING:
            if i.accepting_at is not None and (now - i.accepting_at).total_seconds() < ACCEPTING_STALE_SECONDS:
                return Claim("in_progress", i)
            self._items[item_id] = i = i.model_copy(update={"accepting_at": now})  # taken over: the values stored at the first claim are used
            return Claim("claimed", i)
        if i.status is not ItemStatus.PENDING:
            return Claim("closed", i)
        self._items[item_id] = i = i.model_copy(update={"status": ItemStatus.ACCEPTING, "final_text": text, "sensitivity": sensitivity, "edited": edited, "accepting_at": now})
        return Claim("claimed", i)

    async def finish_accept(self, item_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Item | None:
        i = self._items.get(item_id)
        if i is None:
            return None
        if i.status is ItemStatus.ACCEPTED:
            return i
        if i.status is not ItemStatus.ACCEPTING:
            return None
        self._items[item_id] = done = i.model_copy(update={"status": ItemStatus.ACCEPTED, "record_kind": record_kind, "record_id": record_id, "decided_at": now})
        return done

    async def dismiss(self, item_id: str, *, now: datetime) -> Decision:
        i = self._items.get(item_id)
        if i is None:
            return Decision("missing")
        if i.status is ItemStatus.DISMISSED:
            return Decision("already", i)
        if i.status not in (ItemStatus.PENDING, ItemStatus.NOTED):
            return Decision("closed", i)
        self._items[item_id] = done = i.model_copy(update={"status": ItemStatus.DISMISSED, "decided_at": now})
        return Decision("done", done)

    async def stale_accepting(self, now: datetime) -> list[str]:
        return [i.id for i in self._items.values()
                if i.status is ItemStatus.ACCEPTING and (i.accepting_at is None or (now - i.accepting_at).total_seconds() >= ACCEPTING_STALE_SECONDS)]

    async def drop_meeting(self, meeting_id: str) -> int:
        """The meeting is gone: its runs and items go with it. A task already created from an item stays (it is the owner's record)."""
        gone = [k for k, i in self._items.items() if i.meeting_id == meeting_id]
        for k in gone:
            del self._items[k]
        for k in [k for k, r in self._runs.items() if r.meeting_id == meeting_id]:
            del self._runs[k]
        return len(gone)

    async def close(self) -> None:
        return None
