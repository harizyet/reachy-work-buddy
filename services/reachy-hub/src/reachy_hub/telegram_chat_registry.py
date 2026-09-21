"""Maps our internal user_id to the Telegram chat_id to reply to.

Separate from AgentSession (session_store.py) deliberately: a chat_id is
Telegram-specific delivery plumbing ("which physical endpoint on this
channel"), not part of the channel-agnostic session ADR 0002 describes.
Learned automatically the first time a user messages the bot — nothing
provisions it up front.
"""

from __future__ import annotations

from typing import Protocol


class TelegramChatRegistry(Protocol):
    async def get_chat_id(self, user_id: str) -> int | None: ...
    async def set_chat_id(self, user_id: str, chat_id: int) -> None: ...


class InMemoryTelegramChatRegistry:
    def __init__(self) -> None:
        self._chat_ids: dict[str, int] = {}

    async def get_chat_id(self, user_id: str) -> int | None:
        return self._chat_ids.get(user_id)

    async def set_chat_id(self, user_id: str, chat_id: int) -> None:
        self._chat_ids[user_id] = chat_id
