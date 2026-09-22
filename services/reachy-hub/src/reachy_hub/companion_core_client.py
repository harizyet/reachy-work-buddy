"""HTTP client for companion-core's conversation endpoint.

Per ADR 0002, companion-core is channel-agnostic: it only ever receives a
session_id, conversation_id, and text — never "this came from Telegram" as
anything but an opaque channel label for its own optional use.
"""

from __future__ import annotations

from typing import Any

import httpx


class CompanionCoreClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send_turn(self, session_id: str, conversation_id: str, channel: str, text: str) -> dict[str, Any]:
        resp = await self._client.post(
            "/conversation",
            json={
                "session_id": session_id,
                "conversation_id": conversation_id,
                "channel": channel,
                "text": text,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def due_reminders(self, within_minutes: int = 15) -> list[dict[str, Any]]:
        """Phase 10: events companion-core's calendar store considers due
        for a reminder right now. See companion_core/calendar/reminders.py —
        this is a pure query, not a subscription; reachy-hub calls it
        on demand."""
        resp = await self._client.get("/calendar/reminders/due", params={"within_minutes": within_minutes})
        resp.raise_for_status()
        return resp.json()
