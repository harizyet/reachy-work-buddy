from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    PROFILE = "profile"
    WORKING = "working"
    EPISODIC = "episodic"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    WORK_PRIVATE = "work-private"
    SENSITIVE = "sensitive"


class MemoryRecord(BaseModel):
    """Owned by companion-core (Phase 12). Every stored fact carries
    provenance, sensitivity, and an optional expiry so it can be recalled
    without dumping raw transcripts and without leaking across privacy
    boundaries.
    """

    id: str
    type: MemoryType
    content: str
    source: str
    project_scope: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    sensitivity: Sensitivity = Sensitivity.WORK_PRIVATE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_accessed: datetime | None = None
    expires_at: datetime | None = None
