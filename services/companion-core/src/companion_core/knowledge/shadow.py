"""Measure-only shadow evaluation of knowledge retrieval (Phase 44E follow-up; B1a lexical, provisionally selected by the owner 2026-10-09).

Contract, in the order it is enforced:
- Off unless KNOWLEDGE_SHADOW_ENABLED=true. Off means no object, no query, no file, no connection: the conversation route is the code it was.
- After the production reply is final, a snapshot of plain data is offered. Nothing the shadow computes is ever read by the answer path: it cannot add
  to a prompt, change a reply, the model that answers, a consent state, a draft, a memory, a task, an alarm or the robot, and it has no tool.
- Only qualifying knowledge questions (knowledge/qualify.py) are evaluated; the 50-query criterion counts those evaluated successfully, not chat turns.
- Authorization is deterministic and conservative: the AccessContext comes from trusted turn state only (a spoken turn is a shared speaker, public
  records only; a text turn is the private channel, work-private at most; the sensitive tier is never read; the only destination is local). Nothing a
  model said widens it. Sources are re-read and revalidated by the same code the answer path would use.
- Bounded: one job at a time, a short queue (the oldest job is dropped when full), a per-job timeout, lexical search only (no embedding model), a cap on
  items and the 1,500-token budget. A failure, a timeout or a busy queue only increments a counter.
- Aggregate-only telemetry (knowledge/shadow_telemetry.py): counts and bucketed histograms per hour; no queries, no evidence, no titles, no record ids, no
  session ids. Attempted, admitted, processed, failed and dropped jobs are separate counts that reconcile.
- Reversible: unset the flag and restart; nothing is migrated or written to a database; deleting the telemetry file removes everything it recorded.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from companion_core.knowledge.context import (
    DEFAULT_BUDGET_TOKENS,
    build_context,
    estimate_tokens,
)
from companion_core.knowledge.qualify import qualify
from companion_core.knowledge.retrieval import Retriever
from companion_core.knowledge.routing import choose_path, route_status
from companion_core.knowledge.shadow_telemetry import ShadowTelemetry
from companion_core.planner.store import PlannerStore
from companion_core.semantic.access import access_for_owner
from companion_core.semantic.model import AccessContext, SourceFilters
from companion_core.tasks.store import TaskStore

log = logging.getLogger("companion_core.knowledge_shadow")

DEFAULT_QUEUE = 3
DEFAULT_TIMEOUT = 2.0
VOCABULARY_TTL_SECONDS = 900.0
VOCABULARY_TIMEOUT_SECONDS = 5.0


def shadow_enabled() -> bool:
    return (os.environ.get("KNOWLEDGE_SHADOW_ENABLED") or "").strip().lower() == "true"


@dataclass(frozen=True)
class ShadowTurn:
    """Snapshot taken after the reply is final. Plain data only; the text is used to qualify and run the query and is never stored."""

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
    telemetry: ShadowTelemetry
    vocabulary: Callable[[], Awaitable[frozenset[str]]] | None = None
    queue_size: int = DEFAULT_QUEUE
    timeout_seconds: float = DEFAULT_TIMEOUT
    budget_tokens: int = DEFAULT_BUDGET_TOKENS
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    _pending: collections.deque = field(default_factory=collections.deque)
    _worker: asyncio.Task | None = None
    _terms: frozenset[str] = frozenset()
    _terms_at: float = float("-inf")
    _stopped: bool = False

    # -- lifecycle (called by the application lifespan) -------------------------------------------------------------------------------
    async def start(self) -> None:
        """Prime the vocabulary once; a failure leaves qualification on its record-noun and first-person rules."""
        self.telemetry.prune(force=True)
        await self._refresh_vocabulary()

    async def stop(self) -> None:
        """Stop accepting work, let a running job finish within its limit, count what was still queued, and flush the telemetry."""
        self._stopped = True
        worker = self._worker
        if worker is not None and not worker.done():
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(asyncio.shield(worker), self.timeout_seconds + 1)
            if not worker.done():
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await worker
        if self._pending:
            self.telemetry.count("discarded_at_stop", len(self._pending))
            self._pending.clear()
        self.telemetry.flush()

    async def _refresh_vocabulary(self) -> None:
        if self.vocabulary is None or time.monotonic() - self._terms_at < VOCABULARY_TTL_SECONDS:
            return
        self._terms_at = time.monotonic()  # a failed refresh is not retried every job
        with contextlib.suppress(Exception):
            self._terms = await asyncio.wait_for(self.vocabulary(), VOCABULARY_TIMEOUT_SECONDS)

    # -- request path: constant time, never raises -----------------------------------------------------------------------------------
    def submit(self, turn: ShadowTurn) -> None:
        tel = self.telemetry
        tel.count("attempted")
        if self._stopped:
            tel.count("skipped_empty")  # a late turn at shutdown is neither queued nor qualified
            return
        if turn.production_handler == "slash_command":
            tel.count("skipped_slash")
            return
        if turn.privacy == "sensitive":
            tel.count("skipped_sensitive")
            return
        if not turn.text.strip():
            tel.count("skipped_empty")
            return
        if not qualify(turn.text, known_terms=self._terms).qualifies:
            tel.count("not_qualifying")
            return
        tel.count("admitted")
        if len(self._pending) >= self.queue_size:
            self._pending.popleft()  # drop the oldest: production never waits behind shadow work
            tel.count("dropped_busy")
        self._pending.append(turn)
        if self._worker is None or self._worker.done():
            try:
                self._worker = asyncio.get_running_loop().create_task(self._drain())
            except RuntimeError:
                tel.count("discarded_at_stop", len(self._pending))
                self._pending.clear()

    # -- background ------------------------------------------------------------------------------------------------------------------
    async def _drain(self) -> None:
        while self._pending and not self._stopped:
            turn = self._pending.popleft()
            started = time.perf_counter()
            try:
                await self._refresh_vocabulary()
                measured = await asyncio.wait_for(self._measure(turn), self.timeout_seconds)
            except TimeoutError:
                self.telemetry.count("failed_timeout")
                continue
            except asyncio.CancelledError:
                self.telemetry.count("discarded_at_stop")
                raise
            except Exception:  # noqa: BLE001 - the shadow path must never surface an error
                self.telemetry.count("failed_error")
                log.warning("knowledge shadow job failed", exc_info=False)
                continue
            path, intent, numbers = measured
            self.telemetry.job(path=path, modality=turn.modality, intent=intent, latency_ms=(time.perf_counter() - started) * 1000, measured=numbers)

    async def drain(self) -> None:  # tests
        worker = self._worker
        if worker is not None:
            await asyncio.gather(worker, return_exceptions=True)

    async def _measure(self, turn: ShadowTurn) -> tuple[str, str | None, dict | None]:
        access = access_for(turn)
        path = choose_path(turn.text, attached_meeting=turn.attached_meeting)
        if path == "phase43":  # the attached-meeting path is Phase 43's; the shadow does not run retrieval beside it
            return path, None, None
        now = self.clock()
        intent = None
        if path == "status":
            routed = await route_status(turn.text, access, tasks=self.tasks, planner=self.planner, now=now)
            items, note, candidates, dropped, intent = list(routed.items), routed.note, routed.total, dict(routed.dropped), routed.intent
        else:
            result = await self.retriever.retrieve(turn.text, access, SourceFilters(), temporal="current", limit=10)
            items, note, candidates, dropped = list(result.bundle.items), None, len(result.trace.candidates), dict(result.bundle.dropped)
        built = build_context(items, access, destination="local", budget_tokens=self.budget_tokens, count_tokens=estimate_tokens, now=now,
                              note=note, modality="voice" if turn.modality == "voice" else "text", candidate_count=candidates)
        return path, intent, {
            "items_returned": len(items), "items_in_context": len(built.entries), "evidence_tokens": built.tokens,
            "max_sensitivity": built.max_sensitivity.value, "revalidation_dropped": dropped, "builder_dropped": built.dropped_counts(),
        }

    def summary(self) -> dict:
        return dict(self.telemetry.total)


def shadow_from_env(*, retriever: Retriever, tasks: TaskStore, planner: PlannerStore, adapters: dict | None = None) -> KnowledgeShadow | None:
    """None unless KNOWLEDGE_SHADOW_ENABLED=true and a log path is configured. Bounds come from the environment but are clamped."""
    if not shadow_enabled():
        return None
    path = os.environ.get("KNOWLEDGE_SHADOW_LOG_PATH")
    if not path:
        log.warning("KNOWLEDGE_SHADOW_ENABLED is set but KNOWLEDGE_SHADOW_LOG_PATH is not: the knowledge shadow stays off")
        return None
    from companion_core.knowledge.qualify import build_vocabulary

    async def vocabulary() -> frozenset[str]:
        return await build_vocabulary(adapters or {})

    return KnowledgeShadow(
        retriever=retriever, tasks=tasks, planner=planner,
        telemetry=ShadowTelemetry(path, retention_days=int(os.environ.get("KNOWLEDGE_SHADOW_RETENTION_DAYS", "90"))),
        vocabulary=vocabulary if adapters else None,
        queue_size=min(max(int(os.environ.get("KNOWLEDGE_SHADOW_QUEUE", str(DEFAULT_QUEUE))), 1), 10),
        timeout_seconds=min(max(float(os.environ.get("KNOWLEDGE_SHADOW_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT))), 0.2), 5.0),
    )


__all__ = ["KnowledgeShadow", "ShadowTurn", "access_for", "shadow_enabled", "shadow_from_env"]
