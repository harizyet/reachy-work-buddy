"""HTTP client for a single reachy-embodiment instance.

Wraps the route contract from shared/protocols/embodiment_api.py — the same
constants reachy-embodiment's own app.py uses, so hub and embodiment can
never drift on path spelling (see docs/adr/0003).
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.models.motion import MotionSettings
from shared.protocols import embodiment_api as routes


class EmbodimentClient:
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

    async def health(self) -> dict[str, Any]:
        resp = await self._client.get(routes.HEALTH)
        resp.raise_for_status()
        return resp.json()

    async def get_state(self) -> dict[str, Any]:
        resp = await self._client.get(routes.STATE)
        resp.raise_for_status()
        return resp.json()

    async def get_motion_settings(self) -> dict[str, Any]:
        resp = await self._client.get(routes.MOTION_SETTINGS)
        resp.raise_for_status()
        return resp.json()

    async def set_motion_settings(self, settings: MotionSettings) -> dict[str, Any]:
        resp = await self._client.put(routes.MOTION_SETTINGS, json=settings.model_dump())
        resp.raise_for_status()
        return resp.json()

    async def list_behaviours(self) -> dict[str, str]:
        resp = await self._client.get(routes.BEHAVIOURS)
        resp.raise_for_status()
        return resp.json()

    async def trigger_behaviour(
        self, name: str, *, parameters: dict[str, str] | None = None, correlation_id: str | None = None
    ) -> dict[str, Any]:
        # name is the URL path, the single source of truth for which
        # behaviour is being triggered — the body carries only the extras.
        body: dict[str, Any] = {"parameters": parameters or {}}
        if correlation_id:
            body["correlation_id"] = correlation_id
        resp = await self._client.post(routes.BEHAVIOUR.format(name=name), json=body)
        resp.raise_for_status()
        return resp.json()

    async def heartbeat(self) -> dict[str, Any]:
        resp = await self._client.post(routes.HEARTBEAT)
        resp.raise_for_status()
        return resp.json()

    async def get_camera_frame(self) -> bytes:
        resp = await self._client.get(routes.CAMERA_FRAME)
        resp.raise_for_status()
        return resp.content

    async def set_remote(self, active: bool) -> dict[str, Any]:
        resp = await self._client.post(routes.REMOTE, json={"active": active})
        resp.raise_for_status()
        return resp.json()

    async def play_audio(self, wav_bytes: bytes) -> dict[str, Any]:
        resp = await self._client.post(routes.AUDIO_PLAY, files={"audio": ("reply.wav", wav_bytes, "audio/wav")})
        resp.raise_for_status()
        return resp.json()

    async def daemon_standby(self) -> dict[str, Any]:
        """Phase 22b: owner-requested remote "turn off/standby" command."""
        resp = await self._client.post(routes.DAEMON_STANDBY)
        resp.raise_for_status()
        return resp.json()

    async def daemon_resume(self, *, wake_up: bool = True) -> dict[str, Any]:
        """Resumes a backend previously put into standby. See
        AGENTS.md/docs/deployment.md for the owner-present exception this
        requires when reaching a real daemon — callers into this method
        are responsible for only doing so from an owner-authenticated
        channel, this client doesn't gate it itself."""
        resp = await self._client.post(routes.DAEMON_RESUME, params={"wake_up": wake_up})
        resp.raise_for_status()
        return resp.json()
