"""Phase 44A contract for the knowledge layer (docs/phase-44.md section 4).

Reachy's own ontology: nothing here imports the Ossie adapter, and the adapter never defines these types. The stores stay
authoritative; a KnowledgeItem is a retrieval view of one stored record, identified by a SourceRef. There is no index, no
retrieval and no entity storage yet (44B onward); this module only fixes the shapes so the migration and later stages agree.

Retrieved text is data. Nothing in these types grants authority, and a ContextBundle never selects a model: it only reports
whether the caller must route locally.
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from shared.models.response import Privacy

SourceType = Literal["memory", "document", "meeting", "note", "task", "reminder"]
ItemKind = Literal[
    "memory", "document_chunk", "meeting_segment", "meeting_summary", "meeting_minutes", "note", "task", "reminder"
]
Destination = Literal["local", "deep_local", "cloud"]
DropReason = Literal[
    "missing", "forgotten", "expired", "deleted", "over_ceiling", "out_of_scope", "destination", "budget", "historical"
]


class SourceRef(BaseModel):
    """Composite reference to one stored record or one part of it. `source_id` is the owning store's own id (ids are not
    unique across stores); `locator` picks a part (meeting segment index, "summary"/"minutes", document chunk index)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: SourceType
    source_id: str = Field(min_length=1)
    locator: str | None = None
    # A hash of what an index entry depends on (section 5.3); None when the source cannot supply one.
    source_version: str | None = None

    @property
    def key(self) -> str:
        """Stable identity of the referenced part, independent of the version: "source_type:source_id[#locator]"."""
        base = f"{self.source_type}:{self.source_id}"
        return f"{base}#{self.locator}" if self.locator is not None else base


class Provenance(BaseModel):
    """Where an item came from, taken from retrieval metadata and never from model-written text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: SourceRef
    title: str | None = None
    section: str | None = None
    page: int | None = None  # None until a source can supply one; nothing ingests PDFs yet
    speaker: str | None = None
    start_seconds: float | None = None
    # "model_generated" marks meeting summaries and minutes: derived by a model, so never evidence on their own.
    authority: Literal["source", "model_generated"] = "source"


class KnowledgeItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: SourceRef
    kind: ItemKind
    # Read from the authoritative store when the item is resolved; an index only ever holds match material.
    text: str
    provenance: Provenance
    # The most restrictive of an index copy and the source now: classification can be raised but never silently lowered.
    sensitivity: Privacy = Privacy.WORK_PRIVATE
    # Meeting-derived items must not leave the local models (ADR 0032).
    local_only: bool = False
    # None means unscoped, not public and not "every project" (docs/phase-44.md D8).
    project_scope: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    # Namespaced room for later stages (for example "entity.refs"); core retrieval never reads it.
    extensions: dict[str, Any] = Field(default_factory=dict)


class SourceFilters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_types: frozenset[SourceType] | None = None
    kinds: frozenset[ItemKind] | None = None


class AccessContext(BaseModel):
    """What a retrieval is allowed to see and where the result may be processed.

    Issued by trusted application code (`companion_core.semantic.access.access_for_owner`) from the authenticated request and
    the channel; never a field of a request model, a tool schema or model output, and frozen so nothing widens it in place.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal: str = Field(min_length=1)
    sensitivity_ceiling: Privacy
    # None: no scope restriction. A set: only these project scopes, plus unscoped records (interim single-owner policy).
    project_scopes: frozenset[str] | None = None
    destinations: frozenset[Destination] = frozenset({"local"})
    # False on a shared speaker or any non-private channel (ADR 0006).
    channel_private: bool = True


class ContextBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[KnowledgeItem] = Field(default_factory=list)
    dropped: dict[DropReason, int] = Field(default_factory=dict)
    max_sensitivity: Privacy = Privacy.PUBLIC
    # True when any included item is local_only: the caller must then route to a local model.
    local_only: bool = False
    token_estimate: int = 0


class ContextRetriever(Protocol):
    """The retrieval entry point (implemented from 44D). Revalidates every candidate against its authoritative store."""

    def __call__(
        self,
        query: str,
        access: AccessContext,
        source_filters: SourceFilters | None = None,
        token_budget: int | None = None,
        *,
        temporal: Literal["current", "include_historical"] = "current",
    ) -> Awaitable[ContextBundle]: ...
