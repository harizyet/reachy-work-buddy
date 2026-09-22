from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from shared.models.response import Privacy


class MemoryType(StrEnum):
    PROFILE = "profile"
    WORKING = "working"
    EPISODIC = "episodic"


class MemoryRecord(BaseModel):
    """Owned by companion-core (Phase 12). Every stored fact carries
    provenance, sensitivity, and an optional expiry so it can be recalled
    without dumping raw transcripts and without leaking across privacy
    boundaries.

    `sensitivity` reuses `Privacy` (shared/models/response.py) rather than a
    separate enum — this module originally defined its own `Sensitivity`
    (public/work-private/sensitive), byte-for-byte identical to `Privacy`
    and otherwise unused anywhere in the codebase until Phase 12 actually
    implemented this model. Consolidated when building the real
    implementation rather than carrying forward a duplicate concept.
    """

    id: str
    type: MemoryType
    content: str
    source: str
    project_scope: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    sensitivity: Privacy = Privacy.WORK_PRIVATE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime | None = None
    expires_at: datetime | None = None
