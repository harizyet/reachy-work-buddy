"""HTTP client for reachy-hub. companion-core never talks to
reachy-embodiment directly (see ADR 0001, ADR 0003) — every robot
interaction goes through reachy-hub's robot-registry-backed proxy.
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.protocols.operator_api import ROBOTS, ROBOTS_RESUME, ROBOTS_STANDBY


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

    async def list_robots(self) -> list[dict[str, Any]]:
        resp = await self._client.get(ROBOTS)
        resp.raise_for_status()
        return resp.json()

    async def standby_robots(self) -> list[dict[str, Any]]:
        """Phase 22b: owner-requested remote "turn off/standby" command,
        now reached only via the explicit `/reachy standby` command
        (Phase 24b, companion_core/commands/parser.py). No robot_id —
        reachy-hub loops every registered robot itself (see that route's
        docstring), so this stays consistent with a single-robot
        deployment without core needing to track an id just for this."""
        resp = await self._client.post(ROBOTS_STANDBY)
        resp.raise_for_status()
        return resp.json()

    async def resume_robots(self, *, wake_up: bool = True) -> list[dict[str, Any]]:
        """Resumes every registered robot previously put into standby.
        See AGENTS.md for the owner-present exception this requires when
        driving a real daemon's wake-up motion."""
        resp = await self._client.post(ROBOTS_RESUME, params={"wake_up": wake_up})
        resp.raise_for_status()
        return resp.json()
