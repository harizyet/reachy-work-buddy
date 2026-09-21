from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class InteractionMode(StrEnum):
    """See docs: section 4, Primary operating modes."""

    DESK = "desk"
    OFFICE = "office"
    SILENT = "silent"
    REMOTE = "remote"


class Channel(StrEnum):
    REACHY = "reachy"
    TELEGRAM = "telegram"
    WEB = "web"
    PHONE = "phone"


class PrivacyContext(StrEnum):
    """Ambient privacy state of the user's current physical situation.

    Distinct from AgentResponse.privacy, which is per-message and set by the
    LLM/policy; this is per-session and reflects e.g. "in a meeting."
    """

    PRIVATE = "private"
    SHARED_SPACE = "shared_space"
    MEETING = "meeting"
    UNKNOWN = "unknown"


class AgentSession(BaseModel):
    """Owned by reachy-hub. companion-core sees only session_id + history.

    See docs/adr/0002-agent-session.md.
    """

    session_id: str
    user_id: str
    conversation_id: str
    active_channel: Channel
    interaction_mode: InteractionMode = InteractionMode.DESK
    privacy_context: PrivacyContext = PrivacyContext.UNKNOWN
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active_at: datetime = Field(default_factory=datetime.utcnow)
