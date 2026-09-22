"""Storage for proactive notifications deferred by interruption_policy.py
(action=QUEUE) while the user is occupied (DND/meeting). See
docs/adr/0014-interruption-intelligence.md.

Same Protocol + InMemory + Postgres shape as audit_log.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from shared.models.response import Privacy, Urgency


class QueuedNotification(BaseModel):
    id: str
    user_id: str
    text: str
    privacy: Privacy
    urgency: Urgency
    source_event_id: str | None
    created_at: datetime


class NotificationQueue(Protocol):
    async def enqueue(
        self,
        *,
        user_id: str,
        text: str,
        privacy: Privacy,
        urgency: Urgency,
        source_event_id: str | None,
    ) -> QueuedNotification: ...

    async def list_for_user(self, user_id: str) -> list[QueuedNotification]: ...

    async def clear_for_user(self, user_id: str) -> list[QueuedNotification]: ...


class InMemoryNotificationQueue:
    def __init__(self) -> None:
        self._by_user: dict[str, list[QueuedNotification]] = {}

    async def enqueue(
        self,
        *,
        user_id: str,
        text: str,
        privacy: Privacy,
        urgency: Urgency,
        source_event_id: str | None,
    ) -> QueuedNotification:
        notification = QueuedNotification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            text=text,
            privacy=privacy,
            urgency=urgency,
            source_event_id=source_event_id,
            created_at=datetime.now(UTC),
        )
        self._by_user.setdefault(user_id, []).append(notification)
        return notification

    async def list_for_user(self, user_id: str) -> list[QueuedNotification]:
        return list(self._by_user.get(user_id, []))

    async def clear_for_user(self, user_id: str) -> list[QueuedNotification]:
        return self._by_user.pop(user_id, [])
