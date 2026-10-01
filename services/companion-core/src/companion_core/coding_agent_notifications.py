"""Tracks which completed/failed/lost coding-agent sessions have already
been surfaced to the owner, so reachy-hub's polling of
`GET /coding-agents/completions/due` doesn't re-notify for the same
session on every poll — same "claim it once" shape as
accounts/store.py's `claim_reminders`, but self-contained: coding-agent
sessions have no Postgres-backed store yet either (29.1's store.py is
in-memory), so there is nothing durable to join against. In-memory means a
companion-core restart can re-notify for a session that already finished
before the restart — an acceptable gap for now, matching 29.1's own
documented restart-durability limitation, not a new one.
"""

from __future__ import annotations

from typing import Protocol


class CodingAgentNotificationStore(Protocol):
    async def claim(self, session_id: str) -> bool:
        """True the first time this session_id is claimed, False on every
        later call — the caller notifies only when this returns True."""
        ...


class InMemoryCodingAgentNotificationStore:
    def __init__(self) -> None:
        self._claimed: set[str] = set()

    async def claim(self, session_id: str) -> bool:
        if session_id in self._claimed:
            return False
        self._claimed.add(session_id)
        return True
