"""Thin wrapper around the Telegram Bot API.

Long-polling (getUpdates), not a webhook: reachy-hub doesn't have a public
HTTPS endpoint in V0.1 (no TLS/reverse-proxy auth story yet — see ADR 0006's
Caddy note and docs/plan.md §9), and polling needs nothing but outbound
network access, which is a much smaller deployment requirement for a
homelab service.

Only text messages are handled. Voice notes (Telegram's `message.voice`)
are explicitly out of scope until Phase 8 wires up STT behind a provider
interface — see docs/plan.md's Phase 7/8 split. An inbound voice note is
silently skipped, not stubbed, to avoid a half-built transcription path.
"""

from __future__ import annotations

from typing import Any

import httpx


class TelegramClient:
    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}", transport=transport, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_me(self) -> dict[str, Any]:
        resp = await self._client.get("/getMe")
        resp.raise_for_status()
        return resp.json()["result"]

    async def get_updates(self, *, offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        resp = await self._client.get("/getUpdates", params=params)
        resp.raise_for_status()
        return resp.json()["result"]

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]:
        resp = await self._client.post("/sendMessage", json={"chat_id": chat_id, "text": text})
        resp.raise_for_status()
        return resp.json()["result"]
