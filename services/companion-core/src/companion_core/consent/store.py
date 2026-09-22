"""Pending-confirmation storage. Expiry (like memory's expires_at, calendar
reminders) is enforced at read time only — no background sweep — same
scope discipline used elsewhere in this codebase; an expired-but-not-yet-
swept row is simply never returned as PENDING.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from companion_core.consent.models import (
    ActionScope,
    ConfirmationRequest,
    ConfirmationStatus,
)


def _is_live(request: ConfirmationRequest, now: datetime) -> bool:
    return request.status == ConfirmationStatus.PENDING and request.expires_at > now


class ConfirmationStore(Protocol):
    async def create(
        self, *, action_type: str, target_id: str, description: str, scope: ActionScope, ttl_seconds: int
    ) -> ConfirmationRequest: ...

    async def get(self, confirmation_id: str) -> ConfirmationRequest | None: ...

    async def find_pending(self, action_type: str, query: str) -> ConfirmationRequest | None: ...

    async def confirm(self, confirmation_id: str) -> ConfirmationRequest | None: ...


class InMemoryConfirmationStore:
    def __init__(self) -> None:
        self._requests: dict[str, ConfirmationRequest] = {}

    async def create(
        self, *, action_type: str, target_id: str, description: str, scope: ActionScope, ttl_seconds: int
    ) -> ConfirmationRequest:
        now = datetime.now(UTC)
        request = ConfirmationRequest(
            action_type=action_type,
            target_id=target_id,
            description=description,
            scope=scope,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._requests[request.id] = request
        return request

    async def get(self, confirmation_id: str) -> ConfirmationRequest | None:
        return self._requests.get(confirmation_id)

    async def find_pending(self, action_type: str, query: str) -> ConfirmationRequest | None:
        now = datetime.now(UTC)
        lowered = query.lower()
        candidates = [
            r
            for r in self._requests.values()
            if r.action_type == action_type and _is_live(r, now) and lowered in r.description.lower()
        ]
        candidates.sort(key=lambda r: r.created_at)
        return candidates[0] if candidates else None

    async def confirm(self, confirmation_id: str) -> ConfirmationRequest | None:
        request = self._requests.get(confirmation_id)
        now = datetime.now(UTC)
        if request is None or not _is_live(request, now):
            return None
        request.status = ConfirmationStatus.CONFIRMED
        request.confirmed_at = now
        return request
