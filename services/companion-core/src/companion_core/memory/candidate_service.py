"""Memory candidates: capture and review (Phase 44F; docs/phase-44f-implementation-proposal.md).

CAPTURE proposes a candidate from the owner's own message, after the reply is final, off the request path. It is OFF unless MEMORY_CANDIDATES_ENABLED and MEMORY_CANDIDATES_CAPTURE_ENABLED are
both true. Exclusions come from trusted turn state only: spoken turns, channels that are not owner-authenticated text channels, turns another handler answered, attached meetings, turns
the production classifier labelled sensitive, sensitive text, and privacy mode on or UNKNOWN (the hub lookup fails closed). Assistant text, retrieved records and attachments are not inputs.
REVIEW is the only path to memory: accept calls the existing `add_memory`, writes the existing `memory.created` receipt, and is idempotent (retries, double clicks and crashes cannot create a
second memory: a state machine, a unique index on the memory source, and a lookup before every insert).
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import hashlib
import hmac
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import psycopg

from companion_core.memory import candidate_rules as rules
from companion_core.memory.candidates import (
    ACCEPTED,
    Candidate,
    CandidateStatus,
    CandidateStore,
    new_candidate,
    utcnow,
)
from companion_core.privacy_classifier import classify_privacy
from companion_core.secrets import Keyring
from shared.models.memory import MemoryRecord, MemoryType
from shared.models.receipt import ActionReceipt
from shared.models.response import Privacy

log = logging.getLogger("companion_core.memory_candidates")

ENABLED_FLAG = "MEMORY_CANDIDATES_ENABLED"
CAPTURE_FLAG = "MEMORY_CANDIDATES_CAPTURE_ENABLED"
CHANNELS_ENV = "MEMORY_CANDIDATES_CHANNELS"
DEFAULT_CHANNELS = frozenset({"web", "telegram", "phone"})  # owner-authenticated text channels; "reachy" (the robot in the room) is deliberately absent
DEFAULT_EXPIRY_DAYS: dict[MemoryType, int | None] = {MemoryType.PROFILE: None, MemoryType.WORKING: 30, MemoryType.EPISODIC: 90}
_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}
_RECEIPT_NAMESPACE = uuid.UUID("5f0a6e0e-44f0-4f44-9f44-0a44f0a44f44")
UNSET = object()


def _on(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def candidates_enabled() -> bool:
    return _on(ENABLED_FLAG)


def capture_enabled() -> bool:
    return candidates_enabled() and _on(CAPTURE_FLAG)


def allowed_channels() -> frozenset[str]:
    raw = os.environ.get(CHANNELS_ENV)
    return frozenset(c.strip().lower() for c in raw.split(",") if c.strip()) if raw else DEFAULT_CHANNELS


class KeyedDigester:
    """HMAC-SHA256 digests of normalised text under a key derived from the service keyring: an attacker with the database but not the key cannot test guesses against it. A rotated keyring
    keeps old keys, so lookups try every key id and old suppressions still match."""

    def __init__(self, keyring: Keyring) -> None:
        self._keys = {name: hmac.new(raw, b"memory-candidate-digest-v1", hashlib.sha256).digest() for name, raw in keyring.keys.items()}
        self._active = keyring.active

    def _digest(self, key_id: str, text: str) -> str:
        return hmac.new(self._keys[key_id], rules.normalise(text).encode(), hashlib.sha256).hexdigest()

    def active(self, text: str) -> tuple[str, str]:
        return self._active, self._digest(self._active, text)

    def lookup(self, text: str) -> list[tuple[str, str]]:
        return [(key_id, self._digest(key_id, text)) for key_id in self._keys]


class CandidateError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass(frozen=True)
class CaptureTurn:
    """Plain data offered after the reply is final. `text` is the owner's own message."""

    session_id: str
    conversation_id: str
    turn_index: int
    channel: str
    text: str
    modality: str
    production_handler: str
    attached_meeting: bool
    privacy_label: str


@dataclass
class CandidateCapture:
    store: CandidateStore
    memory: object
    digester: KeyedDigester
    privacy_state: Callable[[], Awaitable[dict | None]]
    channels: frozenset[str] = DEFAULT_CHANNELS
    queue_size: int = 10
    timeout_seconds: float = 3.0
    hourly_cap: int = 5
    daily_cap: int = 20
    clock: Callable[[], datetime] = utcnow
    counters: collections.Counter = field(default_factory=collections.Counter)
    _pending: collections.deque = field(default_factory=collections.deque)
    _worker: asyncio.Task | None = None
    _stopped: bool = False

    async def stop(self) -> None:
        self._stopped = True
        worker = self._worker
        if worker is not None and not worker.done():
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(asyncio.shield(worker), self.timeout_seconds + 1)
            if not worker.done():
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await worker
        self._pending.clear()

    # -- request path: constant time, never raises ---------------------------------------------------------------------------------------
    def submit(self, turn: CaptureTurn) -> None:
        c = self.counters
        c["attempted"] += 1
        if self._stopped:
            return
        if turn.modality != "text":
            c["excluded_spoken"] += 1
        elif turn.channel.lower() not in self.channels:
            c["excluded_channel"] += 1
        elif turn.production_handler != "generic_chat":
            c["excluded_handled"] += 1  # a handler answered it (memory.capture, tasks, commands ...): no double capture
        elif turn.attached_meeting:
            c["excluded_attachment"] += 1
        elif turn.privacy_label == "sensitive":
            c["excluded_sensitive_turn"] += 1
        elif len(turn.text) > rules.MAX_CHARS or not rules.shape_ok(turn.text):
            c["no_match"] += 1
        elif rules.sensitive_hit(turn.text):
            c["excluded_sensitive_text"] += 1
        else:
            proposal = rules.extract(turn.text)
            if proposal is None:
                c["no_match"] += 1
                return
            if len(self._pending) >= self.queue_size:
                self._pending.popleft()
                c["dropped_busy"] += 1
            self._pending.append((turn, proposal))
            c["queued"] += 1
            if self._worker is None or self._worker.done():
                try:
                    self._worker = asyncio.get_running_loop().create_task(self._drain())
                except RuntimeError:
                    self._pending.clear()

    # -- background ----------------------------------------------------------------------------------------------------------------------
    async def _drain(self) -> None:
        while self._pending and not self._stopped:
            turn, proposal = self._pending.popleft()
            try:
                await asyncio.wait_for(self._propose(turn, proposal), self.timeout_seconds)
            except TimeoutError:
                self.counters["failed_timeout"] += 1
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - capture must never surface an error
                self.counters["failed_error"] += 1
                log.warning("memory candidate capture failed")

    async def drain(self) -> None:  # tests
        worker = self._worker
        if worker is not None:
            await asyncio.gather(worker, return_exceptions=True)

    async def _propose(self, turn: CaptureTurn, proposal: rules.Proposal) -> None:
        c = self.counters
        # Privacy mode: ON or UNKNOWN both disable capture. Only an explicit `privacy_mode: false` from the hub allows it.
        try:
            state = await asyncio.wait_for(self.privacy_state(), 1.5)
        except Exception:  # noqa: BLE001
            state = None
        if not isinstance(state, dict) or state.get("privacy_mode") is not False:
            c["excluded_privacy_unknown" if not isinstance(state, dict) or "privacy_mode" not in state else "excluded_privacy_mode"] += 1
            return
        wanted = rules.normalise(proposal.text)
        existing = [rules.normalise(m.content) for m in await self.memory.list_memories()]
        if wanted in existing:
            c["duplicate_memory"] += 1
            return
        now = self.clock()
        key_id, digest = self.digester.active(proposal.text)
        candidate = new_candidate(text=proposal.text, rule_id=proposal.rule_id, rule_version=proposal.rule_version, conversation_id=turn.conversation_id, session_id=turn.session_id,
                                  turn_index=turn.turn_index, channel=turn.channel, proposed_type=proposal.proposed_type, proposed_scope=None, sensitivity=Privacy.WORK_PRIVATE,
                                  digest=digest, digest_key_id=key_id, now=now)
        created, reason = await self.store.create(candidate, self.digester.lookup(proposal.text), hourly_cap=self.hourly_cap, daily_cap=self.daily_cap)
        c["created" if created else f"skipped_{reason}"] += 1

    def summary(self) -> dict[str, int]:
        return dict(self.counters)


@dataclass
class CandidateService:
    store: CandidateStore
    memory: object
    planner: object  # the receipt store (action_receipts)
    clock: Callable[[], datetime] = utcnow

    async def list(self) -> list[dict]:
        return [c.view() for c in await self.store.list_pending(self.clock())]

    async def accept(self, candidate_id: str, *, text: str | None = None, type: MemoryType | None = None, scope=UNSET, sensitivity: Privacy | None = None,
                     expires_in_days=UNSET, acknowledge_lower: bool = False) -> dict:
        now = self.clock()
        c = await self.store.get(candidate_id)
        if c is None:
            raise CandidateError(404, "No such suggestion")
        if c.status in ACCEPTED:
            return await self._result(c)  # a retry or a double click: the same memory, nothing new
        if c.status in (CandidateStatus.REJECTED, CandidateStatus.SUPPRESSED, CandidateStatus.EXPIRED):
            raise CandidateError(409, "This suggestion was already decided")
        if c.status is CandidateStatus.PENDING:
            final_text = rules.clean(text) if text is not None else c.text
            if not final_text or len(final_text) > rules.MAX_CHARS:
                raise CandidateError(422, "The memory must be between 1 and 400 characters")
            final_type = type or c.proposed_type
            final_scope = c.proposed_scope if scope is UNSET else ((scope or "").strip()[:64] or None)
            proposed = c.sensitivity if _RANK[c.sensitivity] >= _RANK[classify_privacy(final_text)] else classify_privacy(final_text)
            final_sensitivity = proposed
            if sensitivity is not None:
                if _RANK[sensitivity] < _RANK[proposed] and not acknowledge_lower:
                    raise CandidateError(422, "Lowering the sensitivity needs an explicit acknowledgement")
                final_sensitivity = sensitivity
            days = DEFAULT_EXPIRY_DAYS[final_type] if expires_in_days is UNSET else expires_in_days
            if days is not None and not (1 <= int(days) <= 3650):
                raise CandidateError(422, "Expiry must be between 1 and 3650 days")
            expires = now + timedelta(days=int(days)) if days is not None else None
            edited = final_text != c.text or final_type != c.proposed_type or final_scope != c.proposed_scope or final_sensitivity != c.sensitivity
        else:  # accepting: a retry; the values stored at the first claim are the ones used
            final_text, final_type, final_scope, final_sensitivity, expires, edited = c.text, c.proposed_type, c.proposed_scope, c.sensitivity, c.expires_memory_at, c.edited
        claim = await self.store.claim_accept(candidate_id, text=final_text, type=final_type, scope=final_scope, sensitivity=final_sensitivity, memory_expires_at=expires,
                                              edited=edited, now=now)
        if claim.outcome == "done":
            return await self._result(claim.candidate)
        if claim.outcome == "in_progress":
            raise CandidateError(409, "This suggestion is being saved; try again in a moment")
        if claim.outcome == "missing":
            raise CandidateError(404, "No such suggestion")
        if claim.outcome != "claimed":
            raise CandidateError(409, "This suggestion can no longer be accepted")
        return await self._finish(claim.candidate)

    async def _finish(self, c: Candidate) -> dict:
        """Create the memory exactly once, write the receipt exactly once, then close the candidate. Safe to run again after any interruption."""
        source = f"candidate:{c.id}"
        record = await self.memory.get_by_source(source)
        if record is None:
            try:
                record = await self.memory.add_memory(content=c.text, source=source, type=c.proposed_type, project_scope=c.proposed_scope, sensitivity=c.sensitivity,
                                                      expires_at=c.expires_memory_at)
            except psycopg.errors.UniqueViolation:  # a concurrent finisher won the unique index on the source: use its memory
                record = await self.memory.get_by_source(source)
                if record is None:
                    raise
        await self._receipt(c, record)
        done = await self.store.finish_accept(c.id, record.id, now=self.clock())
        if done is None:
            raise CandidateError(409, "This suggestion can no longer be accepted")
        return await self._result(done, record)

    async def _receipt(self, c: Candidate, record: MemoryRecord) -> None:
        """The existing memory.created receipt, with an id derived from the candidate so a retry cannot write a second one. A failure is logged and never undoes the accept (ADR 0028)."""
        receipt = ActionReceipt(id=str(uuid.uuid5(_RECEIPT_NAMESPACE, c.id)), action_type="memory.created", source_channel="web", object_type="memory", object_id=record.id,
                                fields={"Sensitivity": str(record.sensitivity.value), "From": "reviewed suggestion", "Edited": "yes" if c.edited else "no"}, notify=False)
        try:
            await self.planner.add_receipt(receipt)
        except psycopg.errors.UniqueViolation:
            return
        except Exception:
            log.exception("could not record the receipt for an accepted memory candidate")

    async def _result(self, c: Candidate, record: MemoryRecord | None = None) -> dict:
        record = record or (await self.memory.get_any(c.memory_id) if c.memory_id else None)
        memory = None
        if record is not None:
            memory = {"id": record.id, "type": record.type.value, "sensitivity": record.sensitivity.value, "content": record.content,
                      "expires_at": record.expires_at.isoformat() if record.expires_at else None}
        return {"candidate": c.view(), "memory": memory}

    async def reject(self, candidate_id: str, *, suppress: bool = False) -> dict:
        decision = await self.store.reject(candidate_id, suppress=suppress, now=self.clock())
        if decision.outcome == "missing":
            raise CandidateError(404, "No such suggestion")
        if decision.outcome == "closed":
            raise CandidateError(409, "This suggestion was already accepted")
        return {"candidate": decision.candidate.view()}

    async def forget_conversation(self, conversation_id: str) -> dict:
        conversation_id = (conversation_id or "").strip()
        if not conversation_id or len(conversation_id) > 200:
            raise CandidateError(422, "A conversation id is required")
        return {"deleted": await self.store.forget_conversation(conversation_id, self.clock())}

    async def reconcile(self) -> int:
        """Finish accepts a crash interrupted: take over each stale `accepting` candidate (one winner) and run the same idempotent finish."""
        done = 0
        now = self.clock()
        for candidate_id in await self.store.stale_accepting(now):
            c = await self.store.get(candidate_id)
            if c is None or c.status is not CandidateStatus.ACCEPTING:
                continue
            claim = await self.store.claim_accept(candidate_id, text=c.text, type=c.proposed_type, scope=c.proposed_scope, sensitivity=c.sensitivity,
                                                  memory_expires_at=c.expires_memory_at, edited=c.edited, now=now)
            if claim.outcome == "claimed":
                with contextlib.suppress(CandidateError):
                    await self._finish(claim.candidate)
                    done += 1
        return done

    async def maintain(self) -> dict[str, int]:
        """Retention: expire pending candidates, purge old decided metadata and counters, and follow the memory: forgotten -> clear the provenance pointer; deleted -> delete the row."""
        out = await self.store.maintain(self.clock())
        cleared = removed = 0
        for candidate_id, memory_id in await self.store.accepted_links():
            record = await self.memory.get_any(memory_id)
            if record is None:
                await self.store.delete(candidate_id)
                removed += 1
            elif record.forgotten_at is not None:
                await self.store.clear_provenance(candidate_id)
                cleared += 1
        return {**out, "provenance_cleared": cleared, "rows_removed_with_memory": removed}


async def maintenance_loop(service: CandidateService, *, interval: float = 3600.0) -> None:
    """Start-up reconciliation and retention, then hourly. Failures are logged and retried at the next interval."""
    while True:
        try:
            await service.reconcile()
            await service.maintain()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("memory candidate maintenance failed")
        await asyncio.sleep(interval)


def digester_from_env() -> KeyedDigester | None:
    """None when the keyring is unavailable: capture then stays off (fail closed)."""
    try:
        return KeyedDigester(Keyring.from_file())
    except Exception:  # noqa: BLE001
        log.warning("memory candidates: the service keyring is unavailable, so capture stays off")
        return None


__all__ = ["CandidateCapture", "CandidateError", "CandidateService", "CaptureTurn", "KeyedDigester", "allowed_channels", "candidates_enabled", "capture_enabled", "digester_from_env",
           "maintenance_loop"]
