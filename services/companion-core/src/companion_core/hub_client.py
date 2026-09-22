"""HTTP client for reachy-hub. companion-core never talks to
reachy-embodiment directly (see ADR 0001, ADR 0003) — every robot
interaction goes through reachy-hub's robot-registry-backed proxy.
"""

from __future__ import annotations

from typing import Any

import httpx


class HubClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
        bearer_token: str | None = None,
    ) -> None:
        # Phase 16/ADR 0013: reachy-hub's /robots/{id}/... routes became
        # auth-gated (REMOTE_UI_TOKEN) once they became part of the
        # remote-control surface. companion-core's /debug/robots/... proxy
        # is a legitimate, trusted internal caller of those same routes, so
        # it needs the same shared token, not a separate one — this is an
        # internal homelab-to-homelab call, not the remote UI itself.
        headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else None
        self._client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout, headers=headers)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_robot_state(self, robot_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/robots/{robot_id}/state")
        resp.raise_for_status()
        return resp.json()

    async def trigger_behaviour(
        self, robot_id: str, name: str, *, parameters: dict[str, str] | None = None
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/robots/{robot_id}/behaviour/{name}", json={"parameters": parameters or {}}
        )
        resp.raise_for_status()
        return resp.json()
