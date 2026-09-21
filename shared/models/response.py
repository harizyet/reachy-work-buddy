from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from shared.models.embodiment import Behaviour


class Privacy(StrEnum):
    PUBLIC = "public"
    WORK_PRIVATE = "work-private"
    SENSITIVE = "sensitive"


class Urgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    URGENT = "urgent"


class PreferredChannel(StrEnum):
    AUTO = "auto"
    REACHY = "reachy"
    TELEGRAM = "telegram"
    PHONE = "phone"


class Citation(BaseModel):
    """Provenance for RAG-backed answers (Phase 13)."""

    source: str
    section: str | None = None
    page: int | None = None


class AgentResponse(BaseModel):
    """companion-core's output. The LLM proposes these fields; a
    deterministic policy in reachy-hub has final authority over routing.

    See docs section 4 (Response routing) and docs/adr/0002-agent-session.md.
    """

    text: str
    privacy: Privacy = Privacy.PUBLIC
    urgency: Urgency = Urgency.NORMAL
    embodiment: Behaviour | None = None
    preferred_channel: PreferredChannel = PreferredChannel.AUTO
    requires_confirmation: bool = False
    citations: list[Citation] = []
