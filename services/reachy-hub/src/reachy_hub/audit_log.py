"""Routing audit trail. See docs/plan.md §9 ("Audit every tool invocation,
approval decision and outbound action") and Phase 9's deliverable ("audit
events").

Every POST /messages / /voice/turn turn writes one entry recording what
routing decision was made and — the part that actually matters for
accountability — whether the privacy override fired. A privacy-sensitive
reply that got routed to Reachy anyway would be exactly the kind of
workplace-privacy leak docs/plan.md §4 is about; the audit trail is what
lets that be checked after the fact, not just trusted at request time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from shared.models.response import Privacy
from shared.models.session import Channel, InteractionMode


class AuditEntry(BaseModel):
    id: str
    user_id: str
    session_id: str
    channel: Channel
    mode: InteractionMode
    privacy: Privacy
    base_channel: Channel
    delivery_channel: Channel
    overridden: bool
    created_at: datetime


class AuditLog(Protocol):
    async def record(
        self,
        *,
        user_id: str,
        session_id: str,
        channel: Channel,
        mode: InteractionMode,
        privacy: Privacy,
        base_channel: Channel,
        delivery_channel: Channel,
    ) -> AuditEntry: ...

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[AuditEntry]: ...


def _new_entry(
    *,
    user_id: str,
    session_id: str,
    channel: Channel,
    mode: InteractionMode,
    privacy: Privacy,
    base_channel: Channel,
    delivery_channel: Channel,
) -> AuditEntry:
    return AuditEntry(
        id=str(uuid.uuid4()),
        user_id=user_id,
        session_id=session_id,
        channel=channel,
        mode=mode,
        privacy=privacy,
        base_channel=base_channel,
        delivery_channel=delivery_channel,
        overridden=base_channel != delivery_channel,
        created_at=datetime.now(UTC),
    )


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._entries: dict[str, list[AuditEntry]] = {}

    async def record(
        self,
        *,
        user_id: str,
        session_id: str,
        channel: Channel,
        mode: InteractionMode,
        privacy: Privacy,
        base_channel: Channel,
        delivery_channel: Channel,
    ) -> AuditEntry:
        entry = _new_entry(
            user_id=user_id,
            session_id=session_id,
            channel=channel,
            mode=mode,
            privacy=privacy,
            base_channel=base_channel,
            delivery_channel=delivery_channel,
        )
        self._entries.setdefault(user_id, []).append(entry)
        return entry

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[AuditEntry]:
        return list(reversed(self._entries.get(user_id, [])))[:limit]
