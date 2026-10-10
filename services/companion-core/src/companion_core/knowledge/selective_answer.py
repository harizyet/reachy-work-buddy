"""Selective answering in the conversation route (Phase 44E integration, owner-approved 2026-10-10; local development only).

An adapter between the existing authorised retrieval layer and the frozen deterministic Stage B-1 pipeline (`answerability_b1`, imported, never edited). No model writes
any word of a reply this module produces.

Outcomes of `SelectiveAnswerer.answer`, decided in this order:

1. `None`: the request is not an eligible knowledge request (an attached meeting, a status question the stores answer, not a knowledge question, or a question the B-1 decomposer
   cannot type at all, or one about attendance, which needs structured data this adapter does not supply). The caller continues exactly as it would with the feature off.
2. an answer: the request is eligible and retrieval succeeded. The reply is B-1's code-written text (a supported value, a conflict, a historical value, or "the records do not say"),
   every citation verified against this turn's revalidated records before release.
3. a fixed failure reply: the request is eligible but retrieval, authorisation (revalidation), citation validation, the index or a timeout failed. Absence of evidence is NOT a failure:
   an empty result from a working index is answered "the records do not say". Once a request is eligible no outcome of this module leads to a model answer.

Access comes from the same trusted turn state as the measure-only shadow (a spoken turn is a shared speaker: public records only; a text turn is the private channel, work-private at
most; the sensitive tier is never read; destination local). The retriever is the existing `Retriever`, whose results are revalidated against the authoritative stores; B-1 receives
only records that survived that, so a restricted record's title, name, value, citation marker or existence cannot appear in a reply or in an error. The reply's sensitivity is the maximum
over the records it cites, and it is released only if the channel ceiling allows that (checked again here).
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from companion_core.knowledge.answerability_b1 import (
    AdmissionPolicy,
    AuthDecision,
    DiscoveryItem,
)
from companion_core.knowledge.answerability_b1.contract import (
    _PLAIN_UNKNOWN,
    _PLAIN_UNSUPPORTED,
)
from companion_core.knowledge.answerability_b1.questions import (
    decompose_question,
    plan_question,
)
from companion_core.knowledge.answerability_b1.registry import Registry
from companion_core.knowledge.answerability_b1.types import State
from companion_core.knowledge.qualify import qualify
from companion_core.knowledge.retrieval import Retriever
from companion_core.knowledge.routing import choose_path
from companion_core.semantic import access as rules
from companion_core.semantic.access import access_for_owner
from companion_core.semantic.model import AccessContext, KnowledgeItem, SourceFilters
from shared.models.response import Privacy

log = logging.getLogger("companion_core.knowledge_selective")

RETRIEVAL_FLAG = "KNOWLEDGE_RETRIEVAL_ENABLED"
SELECTIVE_FLAG = "KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED"
_TRUE = ("1", "true", "yes", "on")

POLICY_VERSION = "selective-1"
ACL_REVISION = 1  # the knowledge layer does not version ACLs; the authorisation here is the revalidation of this very turn, so the decision and the record always agree
RETRIEVAL_LIMIT = 15
DEFAULT_TIMEOUT = 3.0
VOCABULARY_TTL_SECONDS = 900.0
VOCABULARY_TIMEOUT_SECONDS = 5.0
HANDLER_ANSWER = "knowledge.selective"
HANDLER_FAILURE = "knowledge.selective_failure"

# One fixed reply for every failure kind, so a reply never says which stage failed or whether anything restricted exists. It claims no action and no absence.
FAILURE_REPLY = "I couldn't check your records just now, so I haven't answered that. Please try again shortly."

# Owner-approved wording (2026-10-10) for a reply that is wholly "not established" with zero admissible evidence. It never replaces an explicit authoritative absence, a scoped-search negative,
# a conflict, a historical or supported value, a supported part of a partial answer, or a caveat about an unreadable record: those keep B-1's own text.
ZERO_EVIDENCE_REPLY = "I couldn't establish that from the records I was able to check."

_CITE = re.compile(r"\[(E\d+)\]")
_CITE_RUN = re.compile(r"(?: ?\[E\d+\])+")
_AUTHOR = {"memory": "owner", "note": "owner", "task": "owner", "reminder": "owner", "meeting": "attendee", "document": "third_party"}
_SOURCE_NOUN = {"memory": "memory", "note": "note", "task": "task", "reminder": "reminder", "meeting": "meeting", "document": "document"}
_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUE


def retrieval_enabled() -> bool:
    return _flag(RETRIEVAL_FLAG)


def selective_enabled() -> bool:
    return _flag(SELECTIVE_FLAG)


@dataclass(frozen=True)
class Classification:
    """Routing class of one request, decided before any I/O and from the text alone. `klass` is one of: ineligible, typed (every clause typed), ambiguous (some clauses typed, some not), untyped (a
    personal-knowledge question that qualify() accepts but B-1 cannot type). `reason` and `anchors` are fixed category names, never text."""

    klass: str
    reason: str | None = None
    anchors: tuple[str, ...] = ()
    clauses: int = 0
    typed: int = 0


@dataclass(frozen=True)
class Assessment:
    """What the deterministic path would do for a request, as categories only (used by the shadow; carries no text, title, id or reply)."""

    outcome: str  # answered_<state> | answered_mixed | failed_<kind>
    citations: int = 0
    max_sensitivity: str = "none"


@dataclass(frozen=True)
class SelectiveOutcome:
    reply: str
    privacy: Privacy
    handler: str
    cited: tuple[str, ...] = ()  # source keys the reply cites, for tests and the audit log; never sent to the owner


@dataclass
class SelectiveStats:
    """Counters only: no question, answer text, title or record id is ever stored or logged."""

    counts: collections.Counter = field(default_factory=collections.Counter)
    latency_ms: collections.Counter = field(default_factory=collections.Counter)

    def count(self, name: str, n: int = 1) -> None:
        self.counts[name] += n

    def timed(self, started: float) -> None:
        ms = (time.perf_counter() - started) * 1000
        self.latency_ms["le_100" if ms <= 100 else "le_500" if ms <= 500 else "le_1000" if ms <= 1000 else "le_3000" if ms <= 3000 else "gt_3000"] += 1

    def summary(self) -> dict:
        return {"counts": dict(self.counts), "latency_ms": dict(self.latency_ms)}


def access_for(modality: str) -> AccessContext:
    """Trusted turn state only, identical to the shadow's derivation. Nothing the model or the question says widens it."""
    return access_for_owner("selective", channel_private=modality != "voice", allow_sensitive=False, destinations=frozenset({"local"}))


class _Failure(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _aware(value: datetime | None, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return min(value, fallback)


@dataclass
class SelectiveAnswerer:
    retriever: Retriever
    index_count: Callable[[], Awaitable[int]]  # distinguishes "nothing indexed / dependency not ready" (a failure) from "indexed, and the records say nothing" (an answer)
    vocabulary: Callable[[], Awaitable[frozenset[str]]] | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT
    limit: int = RETRIEVAL_LIMIT
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    stats: SelectiveStats = field(default_factory=SelectiveStats)
    _terms: frozenset[str] = frozenset()
    _terms_at: float = float("-inf")
    _refresh: asyncio.Task | None = None
    _registry: Registry = field(default_factory=Registry)

    # -- lifecycle ------------------------------------------------------------------------------------------------------------------
    async def start(self) -> None:
        await self._refresh_vocabulary()

    async def stop(self) -> None:
        task = self._refresh
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _refresh_vocabulary(self) -> None:
        if self.vocabulary is None:
            return
        self._terms_at = time.monotonic()  # a failed refresh is not retried on every turn
        with contextlib.suppress(Exception):
            self._terms = await asyncio.wait_for(self.vocabulary(), VOCABULARY_TIMEOUT_SECONDS)

    def refresh_if_due(self) -> None:
        """Starts a background vocabulary refresh when the last one is older than its time-to-live; never waits."""
        self._maybe_refresh()

    def _maybe_refresh(self) -> None:
        if self.vocabulary is None or time.monotonic() - self._terms_at < VOCABULARY_TTL_SECONDS:
            return
        if self._refresh is None or self._refresh.done():
            self._terms_at = time.monotonic()
            with contextlib.suppress(RuntimeError):
                self._refresh = asyncio.get_running_loop().create_task(self._refresh_vocabulary())

    # -- eligibility (cheap, deterministic, before any I/O) ---------------------------------------------------------------------------
    def classify(self, text: str, *, attached_meeting: bool) -> Classification:
        """Deterministic routing class. Every request that is not a personal-knowledge question B-1 understands in at least one clause is either ineligible or untyped."""
        if attached_meeting:
            return Classification("ineligible", "attached_meeting")
        if not text.strip() or text.lstrip().startswith("/"):
            return Classification("ineligible", "not_knowledge")
        if choose_path(text, attached_meeting=False) != "retrieval":
            return Classification("ineligible", "status_question")
        qualified = qualify(text, known_terms=self._terms)
        if not qualified.qualifies:
            return Classification("ineligible", "not_knowledge")
        anchors = tuple(r for r in qualified.reasons if r != "question")
        decomposition = decompose_question(text, self._registry)
        typed = decomposition.typed
        if not typed:
            return Classification("untyped", "not_understood", anchors, len(decomposition.clauses))
        for component in typed:
            definition = self._registry.relation(component.relation) if component.relation else None
            if definition is not None and definition.structured == "attendees":
                return Classification("untyped", "needs_structured_data", anchors, len(decomposition.clauses), len(typed))
        return Classification("ambiguous" if decomposition.fallback else "typed", None, anchors, len(decomposition.clauses), len(typed))

    def eligible(self, text: str, *, attached_meeting: bool) -> str | None:
        """None when the request is an eligible knowledge request; otherwise the reason it is not (a category, never text). The live path's behaviour is the one it had before `classify` existed."""
        c = self.classify(text, attached_meeting=attached_meeting)
        return None if c.klass in ("typed", "ambiguous") else c.reason

    # -- the answer ---------------------------------------------------------------------------------------------------------------------
    async def answer(self, text: str, *, modality: str, attached_meeting: bool = False) -> SelectiveOutcome | None:
        stats = self.stats
        stats.count("attempted")
        self._maybe_refresh()
        reason = self.eligible(text, attached_meeting=attached_meeting)
        if reason is not None:
            stats.count(f"ineligible_{reason}")
            return None
        stats.count("eligible")
        started = time.perf_counter()
        try:
            outcome = await asyncio.wait_for(self._answer(text, modality), self.timeout_seconds)
        except TimeoutError:
            stats.count("failed_timeout")
            log.warning("selective answering timed out")
            outcome = SelectiveOutcome(FAILURE_REPLY, Privacy.PUBLIC, HANDLER_FAILURE)
        except _Failure as failure:
            stats.count(f"failed_{failure.kind}")
            log.warning("selective answering failed: %s", failure.kind)
            outcome = SelectiveOutcome(FAILURE_REPLY, Privacy.PUBLIC, HANDLER_FAILURE)
        except Exception as exc:  # noqa: BLE001 - an eligible request never reaches a model, whatever failed
            stats.count("failed_error")
            log.warning("selective answering failed: %s", type(exc).__name__)
            outcome = SelectiveOutcome(FAILURE_REPLY, Privacy.PUBLIC, HANDLER_FAILURE)
        stats.timed(started)
        if outcome.handler == HANDLER_ANSWER:
            stats.count("answered")
        return outcome

    async def _answer(self, text: str, modality: str) -> SelectiveOutcome:
        outcome, _n, state, qualified = await self._pipeline(text, modality)
        if qualified:
            self.stats.count("qualified_zero_evidence")
        self.stats.count(f"state_{state}")
        return outcome

    async def assess(self, text: str, modality: str, *, timeout: float | None = None) -> Assessment:
        """The categories of what the deterministic path would do, with the same access, retrieval, revalidation and verification as the live path and no effect on its counters. Never raises."""
        try:
            outcome, n, state, _q = await asyncio.wait_for(self._pipeline(text, modality), timeout or self.timeout_seconds)
        except TimeoutError:
            return Assessment("failed_timeout")
        except _Failure as failure:
            return Assessment(f"failed_{failure.kind}")
        except Exception:  # noqa: BLE001 - an assessment never raises into its caller
            return Assessment("failed_error")
        return Assessment(f"answered_{state}", n, outcome.privacy.value if outcome.cited else "none")

    async def _pipeline(self, text: str, modality: str):
        """-> (outcome, citation count, dominant state name, zero-evidence-qualified). Raises _Failure for every dependency, authorisation, pipeline or verification failure."""
        access = access_for(modality)
        now = self.clock()
        try:
            if await self.index_count() <= 0:
                raise _Failure("not_ready")
            result = await self.retriever.retrieve(text, access, SourceFilters(), temporal="current", limit=self.limit)
        except _Failure:
            raise
        except Exception as exc:
            raise _Failure("retrieval") from exc
        discovery, auths, eids, by_eid = self._discovery(result.bundle.items, access, now)
        try:
            registry = self._registry
            pool = registry.entities.harvest([d.text for d in discovery])
            learned = Registry(entities=registry.entities.with_entries(pool))
            plan, _ = plan_question(
                text, learned, discovery, auths, now=now, eids=eids, policy=AdmissionPolicy(expected_policy_version=POLICY_VERSION, allow_context=True, qualified_object_check=True),
                pool_mentions=pool)
        except Exception as exc:
            raise _Failure("pipeline") from exc
        reply = plan.answer
        if not reply.strip():
            raise _Failure("pipeline")
        cited = self._verify(reply, plan, by_eid, access)
        states = sorted({c.state.value.lower() for c in plan.claims})
        state = states[0] if len(states) == 1 else "mixed"
        qualified = not cited and bool(plan.claims) and all(
            (c.state is State.UNSUPPORTED and c.reasons == _PLAIN_UNSUPPORTED) or (c.state is State.NEGATIVE_UNSUPPORTED and c.reasons == _PLAIN_UNKNOWN) for c in plan.claims)
        if qualified:
            reply, state = ZERO_EVIDENCE_REPLY, "unsupported"  # wholly unsupported with nothing admissible: the approved qualification; nothing else is overwritten
        reply, by_eid, cited = _renumber(reply, by_eid, cited)
        privacy = Privacy.PUBLIC
        if cited:
            privacy = rules.effective_sensitivity(*(by_eid[e].sensitivity for e in cited))
        if modality == "voice":
            reply = _CITE_RUN.sub("", reply)  # ids are not read aloud
        else:
            reply = reply + _sources_line(cited, by_eid)
        return SelectiveOutcome(reply, privacy, HANDLER_ANSWER, tuple(by_eid[e].ref.key for e in cited)), len(cited), state, qualified

    def _discovery(self, items: list[KnowledgeItem], access: AccessContext, now: datetime):
        """KnowledgeItem -> DiscoveryItem, authorised only because revalidation just passed it. Anything this adapter cannot state with the provenance B-1 needs is left out (counted)."""
        discovery: list[DiscoveryItem] = []
        auths: dict[str, AuthDecision] = {}
        eids: dict[str, str] = {}
        by_eid: dict[str, KnowledgeItem] = {}
        for item in items:
            key = item.ref.key
            if item.provenance.authority != "source":
                self.stats.count("excluded_model_generated")  # a model-written summary is never evidence
            elif item.valid_from is not None and _aware(item.valid_from, now + timedelta(days=36500)) > now:
                self.stats.count("excluded_not_yet_effective")
            elif _RANK[item.sensitivity] > _RANK[access.sensitivity_ceiling]:
                self.stats.count("excluded_over_ceiling")  # defence in depth: revalidation already enforces this
            else:
                eid = f"E{len(eids) + 1}"
                eids[key], by_eid[eid] = eid, item
                discovery.append(DiscoveryItem(
                    key, item.text, {"store": item.ref.source_type, "record_id": item.ref.source_id, "author_class": _AUTHOR[item.ref.source_type],
                                     "created_at": _aware(item.observed_at, now), "retrieved_at": now, "acl_revision": ACL_REVISION}, item.provenance.title or ""))
                auths[key] = AuthDecision(True, now, POLICY_VERSION, ACL_REVISION)
        return discovery, auths, eids, by_eid

    def _verify(self, reply: str, plan, by_eid: dict[str, KnowledgeItem], access: AccessContext) -> list[str]:
        """Every citation in the reply (and in each claim's mapping) must name a record revalidated for this turn, within the channel's ceiling. Returns the cited ids in order."""
        cited: list[str] = []
        for eid in _CITE.findall(reply):
            if eid not in by_eid:
                raise _Failure("verify")
            if eid not in cited:
                cited.append(eid)
        for claim in plan.claims:
            for _value, ids in claim.assertable:
                if any(i not in by_eid for i in ids):
                    raise _Failure("verify")
        if any(_RANK[by_eid[e].sensitivity] > _RANK[access.sensitivity_ceiling] for e in cited):
            raise _Failure("verify")
        return cited


def _renumber(reply: str, by_eid: dict[str, KnowledgeItem], cited: list[str]) -> tuple[str, dict[str, KnowledgeItem], list[str]]:
    """Citation markers are renumbered E1, E2... in order of appearance in the reply, so a marker never reveals how many other records were retrieved or ranked ahead of the cited one."""
    mapping = {old: f"E{n}" for n, old in enumerate(cited, 1)}
    return _CITE.sub(lambda m: f"[{mapping[m.group(1)]}]", reply), {new: by_eid[old] for old, new in mapping.items()}, list(mapping.values())


def _sources_line(cited: list[str], by_eid: dict[str, KnowledgeItem]) -> str:
    """Resolves the [E#] markers for the owner: only the cited, authorised records, by title (or kind), nothing from their text."""
    if not cited:
        return ""
    parts = []
    for eid in cited:
        item = by_eid[eid]
        title = " ".join((item.provenance.title or "").split())[:80]
        parts.append(f"[{eid}] {title + ' (' + _SOURCE_NOUN[item.ref.source_type] + ')' if title else 'a ' + _SOURCE_NOUN[item.ref.source_type]}")
    return "\n\nSources: " + "; ".join(parts) + "."


def from_env(*, retriever: Retriever, index_count: Callable[[], Awaitable[int]], vocabulary=None) -> SelectiveAnswerer | None:
    """None unless BOTH flags are true. Selective answering without retrieval is inert (one warning): it never builds a private retriever."""
    if not selective_enabled():
        return None
    if not retrieval_enabled():
        log.warning("%s is set but %s is not: selective answering stays off", SELECTIVE_FLAG, RETRIEVAL_FLAG)
        return None
    timeout = min(max(float(os.environ.get("KNOWLEDGE_SELECTIVE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT))), 0.2), 10.0)
    return SelectiveAnswerer(retriever=retriever, index_count=index_count, vocabulary=vocabulary, timeout_seconds=timeout)


__all__ = [
    "FAILURE_REPLY",
    "HANDLER_ANSWER",
    "HANDLER_FAILURE",
    "RETRIEVAL_FLAG",
    "SELECTIVE_FLAG",
    "ZERO_EVIDENCE_REPLY",
    "Assessment",
    "Classification",
    "SelectiveAnswerer",
    "SelectiveOutcome",
    "SelectiveStats",
    "access_for",
    "from_env",
    "retrieval_enabled",
    "selective_enabled",
]
