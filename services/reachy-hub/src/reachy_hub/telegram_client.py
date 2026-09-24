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
        payload = resp.json()
        updates = payload.get("result") if isinstance(payload, dict) else None
        if (not isinstance(payload, dict) or payload.get("ok") is not True
                or not isinstance(updates, list)
                or any(not isinstance(u, dict) or type(u.get("update_id")) is not int for u in updates)):
            raise ValueError("Invalid Telegram polling response")
        return updates

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]:
        resp = await self._client.post("/sendMessage", json={"chat_id": chat_id, "text": text})
        resp.raise_for_status()
        return resp.json()["result"]

    async def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        """Registers the bot's command menu (Telegram's setMyCommands).
        Phase 24b: `BotCommand.command` cannot contain a space, so this
        registers the flat aliases (`standby`, `wake`, `reachy_status`),
        not the namespaced `/reachy <action>` form — see
        companion_core/commands/parser.py's TELEGRAM_ALIASES, which both
        forms parse to identically."""
        resp = await self._client.post("/setMyCommands", json={"commands": commands})
        resp.raise_for_status()
