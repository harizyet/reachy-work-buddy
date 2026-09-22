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


class InputModality(StrEnum):
    """Was this turn typed or spoken? Distinct from Channel, which means
    "which client/device" — voice input on the Reachy channel and a future
    typed-on-Reachy-touchscreen message would share `channel=reachy` but
    differ here. Exists specifically so destructive-action confirmation
    (docs/adr/0011) can refuse anything that arrived as VOICE: voice input
    is unauthenticated ambient audio, easy to spoof or mishear, and this
    system's one hard security rule is that it never authorizes a
    destructive action from it, textual-consent-only. Threaded end to end:
    reachy-hub's InboundMessage -> handle_inbound_message ->
    CompanionCoreClient.send_turn -> companion-core's
    ConversationTurnRequest. Only `voice_turn` (real STT transcription)
    ever constructs VOICE; every other inbound path defaults to TEXT."""

    TEXT = "text"
    VOICE = "voice"


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
