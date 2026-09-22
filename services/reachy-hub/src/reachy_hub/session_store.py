"""AgentSession storage: one persistent session per user, shared across
channels. See docs/adr/0002-agent-session.md.

One active session per user is a deliberate V0.1 simplification (docs plan
§4/§7: "Maintain one persistent conversation... across Reachy, Telegram,
web, and phone-call interfaces") — not a general multi-conversation model.
Revisit if/when a real product need for concurrent conversations per user
shows up; don't build that ahead of time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from shared.models.session import AgentSession, Channel, InteractionMode, PrivacyContext


class SessionStore(Protocol):
    async def get_by_user(self, user_id: str) -> AgentSession | None: ...
    async def get_or_create(self, user_id: str, channel: Channel) -> AgentSession: ...
    async def touch_channel(self, session: AgentSession, channel: Channel) -> AgentSession: ...
    async def set_mode(self, session: AgentSession, mode: InteractionMode) -> AgentSession: ...
    async def set_dnd(self, session: AgentSession, dnd: bool) -> AgentSession: ...
    async def set_privacy_context(self, session: AgentSession, privacy_context: PrivacyContext) -> AgentSession: ...
    async def record_interruption(self, session: AgentSession, at: datetime) -> AgentSession: ...


def _new_session(user_id: str, channel: Channel) -> AgentSession:
    now = datetime.now(UTC)
    return AgentSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        conversation_id=str(uuid.uuid4()),
        active_channel=channel,
        created_at=now,
        last_active_at=now,
    )


class InMemorySessionStore:
    def __init__(self) -> None:
        self._by_user: dict[str, AgentSession] = {}

    async def get_by_user(self, user_id: str) -> AgentSession | None:
        return self._by_user.get(user_id)

    async def get_or_create(self, user_id: str, channel: Channel) -> AgentSession:
        existing = self._by_user.get(user_id)
        if existing is not None:
            return existing
        session = _new_session(user_id, channel)
        self._by_user[user_id] = session
        return session

    async def touch_channel(self, session: AgentSession, channel: Channel) -> AgentSession:
        session.active_channel = channel
        session.last_active_at = datetime.now(UTC)
        self._by_user[session.user_id] = session
        return session

    async def set_mode(self, session: AgentSession, mode: InteractionMode) -> AgentSession:
        session.interaction_mode = mode
        session.last_active_at = datetime.now(UTC)
        self._by_user[session.user_id] = session
        return session

    async def set_dnd(self, session: AgentSession, dnd: bool) -> AgentSession:
        session.dnd = dnd
        session.last_active_at = datetime.now(UTC)
        self._by_user[session.user_id] = session
        return session

    async def set_privacy_context(self, session: AgentSession, privacy_context: PrivacyContext) -> AgentSession:
        session.privacy_context = privacy_context
        session.last_active_at = datetime.now(UTC)
        self._by_user[session.user_id] = session
        return session

    async def record_interruption(self, session: AgentSession, at: datetime) -> AgentSession:
        session.last_interruption_at = at
        self._by_user[session.user_id] = session
        return session
