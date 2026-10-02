"""HTTP client for coding-agent-service (Phase 29). ADR 0001 allows a
direct sibling-service HTTP call like this one — same shape as
hub_client.py (companion-core -> reachy-hub) and meetings/speech_clients.py
(companion-core -> the speech sidecars). companion-core reads
session/usage state through this client and, only for an explicit
`/coding_reply` command, relays the owner's answer to resume a waiting
session; it never starts or stops one.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from shared.protocols.coding_agent import (
    PROVIDER_ALLOWANCE,
    SERVICE_HEADER,
    SESSION_RESUME,
    SESSION_USAGE,
    SESSIONS,
    TERMINAL_SESSIONS,
)


class CodingAgentServiceClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        service_token: str | None = None,
    ) -> None:
        token = service_token or os.environ.get("CODING_AGENT_SERVICE_TOKEN")
        self._client = httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=timeout,
            headers={SERVICE_HEADER: token} if token else {},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_sessions(self) -> list[dict[str, Any]]:
        resp = await self._client.get(SESSIONS)
        resp.raise_for_status()
        return resp.json()

    async def list_terminal_sessions(self) -> list[dict[str, Any]]:
        resp = await self._client.get(TERMINAL_SESSIONS)
        resp.raise_for_status()
        return resp.json()

    async def resume_session(self, session_id: str, instruction: str) -> dict[str, Any]:
        """The owner's reply, verbatim, resuming the same provider session."""
        resp = await self._client.post(
            SESSION_RESUME.format(session_id=session_id), json={"instruction": instruction}
        )
        resp.raise_for_status()
        return resp.json()

    async def get_usage(self, session_id: str) -> dict[str, Any]:
        resp = await self._client.get(SESSION_USAGE.format(session_id=session_id))
        resp.raise_for_status()
        return resp.json()

    async def get_allowance(self, provider: str) -> dict[str, Any]:
        resp = await self._client.get(PROVIDER_ALLOWANCE.format(provider=provider))
        resp.raise_for_status()
        return resp.json()
