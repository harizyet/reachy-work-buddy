"""Retrieval-time source revalidation (Phase 44B, docs/phase-44.md D3 and section 4). **Non-negotiable.**

The index is derived data and can be stale: a memory forgotten a moment ago, a meeting deleted, a note reclassified, a document edited
while the worker was behind. So nothing from the index is returned as it is. Every candidate is checked against its authoritative
store *now*: it must still exist and be visible; its classification is the more restrictive of the index copy and the source (an index
can never downgrade a source); the text and provenance are read from the source; and then the caller's AccessContext is applied. What
survives is a ContextBundle; what does not is counted by reason, never returned.

Candidates come from search (44D). This module needs only a candidate's reference and the metadata the index holds about it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from companion_core.knowledge.sources import Indexable, SourceAdapter, SourceState
from companion_core.semantic import access
from companion_core.semantic.model import (
    AccessContext,
    ContextBundle,
    DropReason,
    KnowledgeItem,
    Provenance,
    SourceRef,
)
from shared.models.response import Privacy


@dataclass(frozen=True)
class Candidate:
    """What the index says about a part of a source. Only `sensitivity` is used from it (to keep the stricter label); everything else
    is read from the source."""

    ref: SourceRef
    sensitivity: Privacy = Privacy.PUBLIC


_STATUS_REASON: dict[str, DropReason] = {
    "missing": "missing", "forgotten": "forgotten", "expired": "expired", "hidden": "deleted",
}


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _knowledge_item(indexable: Indexable, sensitivity: Privacy) -> KnowledgeItem:
    return KnowledgeItem(
        ref=indexable.ref, kind=indexable.kind, text=indexable.text,
        provenance=Provenance(
            ref=indexable.ref, title=indexable.title, section=indexable.section, speaker=indexable.speaker,
            start_seconds=indexable.start_seconds, authority=indexable.authority,
        ),
        sensitivity=sensitivity, local_only=indexable.local_only, project_scope=indexable.project_scope,
        confidence=indexable.confidence, observed_at=indexable.observed_at, valid_from=indexable.valid_from,
        valid_until=indexable.valid_until,
    )


async def revalidate(
    candidates: Sequence[Candidate],
    access_context: AccessContext,
    adapters: dict[str, SourceAdapter],
    *,
    temporal: Literal["current", "include_historical"] = "current",
    now: datetime | None = None,
) -> ContextBundle:
    """Candidate order is preserved. Each source is read once, however many of its parts are candidates."""
    now = now or datetime.now(UTC)
    states: dict[tuple[str, str], SourceState] = {}
    items: list[KnowledgeItem] = []
    dropped: dict[DropReason, int] = {}

    def drop(reason: DropReason) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    seen: set[str] = set()
    for candidate in candidates:
        if candidate.ref.key in seen:
            continue
        seen.add(candidate.ref.key)
        adapter = adapters.get(candidate.ref.source_type)
        if adapter is None:
            drop("missing")
            continue
        key = (candidate.ref.source_type, candidate.ref.source_id)
        if key not in states:
            states[key] = await adapter.state(candidate.ref.source_id)
        state = states[key]
        if state.status != "visible":
            drop(_STATUS_REASON[state.status])
            continue
        current = next((i for i in state.items if i.ref.key == candidate.ref.key), None)
        if current is None:  # the part no longer exists (a segment removed, a chunk replaced)
            drop("missing")
            continue
        if temporal == "current" and current.valid_until is not None and current.valid_until <= now:
            drop("historical")
            continue
        item = _knowledge_item(current, access.effective_sensitivity(candidate.sensitivity, current.sensitivity))
        reason = access.decide(access_context, item)
        if reason is not None:
            drop(reason)
            continue
        items.append(item)

    return ContextBundle(
        items=items, dropped=dropped,
        max_sensitivity=access.effective_sensitivity(Privacy.PUBLIC, *(i.sensitivity for i in items)),
        local_only=any(i.local_only for i in items), token_estimate=sum(_tokens(i.text) for i in items),
    )
