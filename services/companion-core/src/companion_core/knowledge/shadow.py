"""Measure-only shadow evaluation of knowledge retrieval (Phase 44E follow-up; B1a lexical, provisionally selected by the owner 2026-10-09).

Contract, in the order it is enforced:
- Off unless KNOWLEDGE_SHADOW_ENABLED=true. Off means no object, no query, no file, no connection: the conversation route is byte-for-byte the code
  it was.
- After the production reply is final, a snapshot of plain data is queued. Nothing the shadow computes is ever read by the answer path: it
  cannot add to a prompt, change a reply, a consent state, a draft, a memory, a task, an alarm or the robot, and it has no tool.
- Authorization is deterministic and conservative: the AccessContext is built from trusted turn state only (a spoken turn is treated as a shared
  speaker, public records only; a text turn as the owner's private channel, work-private at most; the sensitive tier is never read; the only
  destination is local). Nothing a model said widens it. Sources are re-read and revalidated by the same code the answer path would use.
- Bounded: one job at a time, a short queue (the oldest job is dropped when full), a per-job timeout, lexical search only (no embedding model is
  loaded), a hard cap of items and the 1,500-token budget. A failure, a timeout or a busy queue only increments a counter.
- Minimal telemetry: numbers and categories only. No query text, no query hash, no record text, no source ids, no titles. The file is created
  0600. Counters are exposed in memory for tests and logged on shutdown; there is no new endpoint.
- Reversible: unset the flag and restart; nothing is migrated or written to a database; deleting the telemetry file removes everything it ever
  recorded. The only thing it reads is the existing index and the authoritative stores.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import hashlib
import json
import logging
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from companion_core.knowledge.context import (
    DEFAULT_BUDGET_TOKENS,
    build_context,
    estimate_tokens,
)
from companion_core.knowledge.retrieval import Retriever
from companion_core.knowledge.routing import choose_path, route_status
from companion_core.planner.store import PlannerStore
from companion_core.semantic.access import access_for_owner
from companion_core.semantic.model import AccessContext, SourceFilters
from companion_core.tasks.store import TaskStore

log = logging.getLogger("companion_core.knowledge_shadow")

DEFAULT_QUEUE = 3
DEFAULT_TIMEOUT = 2.0
SKIPPED_HANDLERS = {"slash_command"}


def shadow_enabled() -> bool:
    return (os.environ.get("KNOWLEDGE_SHADOW_ENABLED") or "").strip().lower() == "true"


@dataclass(frozen=True)
class ShadowTurn:
    """Snapshot taken after the reply is final. Plain data only; the text is used to run the shadow query and is never stored."""

    session_id: str
    text: str
    modality: str  # "text" or "voice"
    privacy: str  # the production label of the turn
    production_handler: str
    attached_meeting: bool


def access_for(turn: ShadowTurn) -> AccessContext:
    """Deterministic, from trusted turn state only. Spoken turns may be on a shared speaker, so they see public records only."""
    return access_for_owner("shadow", channel_private=turn.modality != "voice", allow_sensitive=False, destinations=frozenset({"local"}))


@dataclass
class KnowledgeShadow:
    retriever: Retriever
    tasks: TaskStore
    planner: PlannerStore
    log_path: str
    queue_size: int = DEFAULT_QUEUE
    timeout_seconds: float = DEFAULT_TIMEOUT
    budget_tokens: int = DEFAULT_BUDGET_TOKENS
    clock: object = lambda: datetime.now(UTC)
    counters: Counter = field(default_factory=Counter)
    _pending: collections.deque = field(default_factory=collections.deque)
    _worker: asyncio.Task | None = None

    def submit(self, turn: ShadowTurn) -> None:
        """Best effort and non-blocking: never raises, never awaits the work, never builds a backlog."""
        if turn.production_handler in SKIPPED_HANDLERS or turn.privacy == "sensitive" or not turn.text.strip():
            self.counters["skipped"] += 1
            return
        if len(self._pending) >= self.queue_size:
            self._pending.popleft()  # drop the oldest: production never waits behind shadow work
            self.counters["dropped_busy"] += 1
        self._pending.append(turn)
        if self._worker is None or self._worker.done():
            try:
                self._worker = asyncio.get_running_loop().create_task(self._drain())
            except RuntimeError:
                self._pending.clear()

    async def _drain(self) -> None:
        while self._pending:
            turn = self._pending.popleft()
            started = time.perf_counter()
            try:
                row = await asyncio.wait_for(self._measure(turn), self.timeout_seconds)
                row["outcome"] = "ok"
            except TimeoutError:
                row = {"outcome": "timeout"}
                self.counters["timeout"] += 1
            except Exception:  # noqa: BLE001 - the shadow path must never surface an error
                row = {"outcome": "error"}
                self.counters["error"] += 1
                log.warning("knowledge shadow error", exc_info=False)
            row["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
            with contextlib.suppress(OSError):
                self._write(turn, row)

    async def drain(self) -> None:  # tests and shutdown
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)

    async def _measure(self, turn: ShadowTurn) -> dict:
        access = access_for(turn)
        path = choose_path(turn.text, attached_meeting=turn.attached_meeting)
        row: dict = {"path": path}
        now = self.clock()
        if path == "phase43":  # the attached-meeting path is Phase 43's; the shadow does not run retrieval beside it
            return row
        t = time.perf_counter()
        if path == "status":
            routed = await route_status(turn.text, access, tasks=self.tasks, planner=self.planner, now=now)
            items, note, candidates, dropped = list(routed.items), routed.note, routed.total, dict(routed.dropped)
            row["intent"] = routed.intent
        else:
            result = await self.retriever.retrieve(turn.text, access, SourceFilters(), temporal="current", limit=10)
            items, note, candidates, dropped = list(result.bundle.items), None, len(result.trace.candidates), dict(result.bundle.dropped)
        row["retrieval_ms"] = round((time.perf_counter() - t) * 1000, 1)
        t = time.perf_counter()
        built = build_context(items, access, destination="local", budget_tokens=self.budget_tokens, count_tokens=estimate_tokens, now=now,
                              note=note, modality="voice" if turn.modality == "voice" else "text", candidate_count=candidates)
        row["build_ms"] = round((time.perf_counter() - t) * 1000, 1)
        kinds = Counter(e.kind for e in built.entries)
        row.update({
            "candidates": candidates, "items_returned": len(items), "items_in_context": len(built.entries), "kinds": dict(kinds),
            "evidence_tokens": built.tokens, "max_sensitivity": built.max_sensitivity.value, "local_only": built.local_only,
            "revalidation_dropped": dropped, "builder_dropped": built.dropped_counts(),
            "truncated": any(e.truncated for e in built.entries), "instruction_like": sum(e.instruction_like for e in built.entries),
        })
        self.counters[f"path:{path}"] += 1
        self.counters["measured"] += 1
        if not items:
            self.counters["empty"] += 1
        return row

    def _write(self, turn: ShadowTurn, row: dict) -> None:
        row = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),  # minute resolution
            "session": hashlib.sha256(turn.session_id.encode()).hexdigest()[:12],  # one-way label so sessions can be counted, never joined to text
            "modality": turn.modality, "query_len": len(turn.text), **row,
        }
        fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def summary(self) -> dict:
        return dict(self.counters)


def shadow_from_env(*, retriever: Retriever, tasks: TaskStore, planner: PlannerStore) -> KnowledgeShadow | None:
    """None unless KNOWLEDGE_SHADOW_ENABLED=true and a log path is configured. Bounds come from the environment but are clamped."""
    if not shadow_enabled():
        return None
    path = os.environ.get("KNOWLEDGE_SHADOW_LOG_PATH")
    if not path:
        log.warning("KNOWLEDGE_SHADOW_ENABLED is set but KNOWLEDGE_SHADOW_LOG_PATH is not: the knowledge shadow stays off")
        return None
    queue = min(max(int(os.environ.get("KNOWLEDGE_SHADOW_QUEUE", DEFAULT_QUEUE)), 1), 10)
    timeout = min(max(float(os.environ.get("KNOWLEDGE_SHADOW_TIMEOUT_SECONDS", DEFAULT_TIMEOUT)), 0.2), 5.0)
    return KnowledgeShadow(retriever=retriever, tasks=tasks, planner=planner, log_path=path, queue_size=queue, timeout_seconds=timeout)


__all__ = ["KnowledgeShadow", "ShadowTurn", "access_for", "shadow_enabled", "shadow_from_env"]
