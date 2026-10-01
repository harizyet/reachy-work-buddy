"""HTTP client for coding-agent-service's owner-facing credential surface
(Phase 29.19). Separate from CompanionCoreClient's SERVICE_HEADER —
coding-agent-service uses its own shared secret (shared.protocols.
coding_agent.SERVICE_HEADER), deliberately not reused from accounts, so a
leaked credential-service token cannot also authenticate account calls.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from shared.protocols.coding_agent import (
    PROVIDER_CREDENTIAL,
    PROVIDER_CREDENTIALS,
    SERVICE_HEADER,
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

    async def list_credentials(self) -> list[dict[str, Any]]:
        resp = await self._client.get(PROVIDER_CREDENTIALS)
        resp.raise_for_status()
        return resp.json()

    async def get_credential(self, provider: str) -> dict[str, Any] | None:
        resp = await self._client.get(PROVIDER_CREDENTIAL.format(provider=provider))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def set_credential(self, provider: str, kind: str, value: str) -> dict[str, Any]:
        resp = await self._client.put(
            PROVIDER_CREDENTIAL.format(provider=provider), json={"kind": kind, "value": value}
        )
        resp.raise_for_status()
        return resp.json()

    async def clear_credential(self, provider: str) -> dict[str, Any]:
        resp = await self._client.delete(PROVIDER_CREDENTIAL.format(provider=provider))
        resp.raise_for_status()
        return resp.json()
