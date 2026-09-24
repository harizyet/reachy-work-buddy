"""In-memory per-session transcript.

Not durable work memory — Phase 12's MemoryRecord store is separate.
This transcript provides shared cross-channel context (ADR 0002) and,
since Phase 19, user/assistant messages for the configured chat provider.
It resets with the process; durable work facts remain in the memory store.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from shared.models.response import Privacy


@dataclass
class Turn:
    channel: str
    text: str


class ConversationStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.generation = 0
        self._turns: dict[str, list[Turn]] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._privacy: dict[str, Privacy] = {}
        self._messages: dict[str, list[dict[str, str]]] = {}

    def clear(self) -> None:
        """Remove provider-derived context when an account connection is removed."""
        with self._lock:
            self.generation += 1
            self._turns.clear()
            self._messages.clear()
            self._privacy.clear()

    def append(self, session_id: str, channel: str, text: str) -> list[Turn]:
        with self._lock:
            turns = self._turns.setdefault(session_id, [])
            turns.append(Turn(channel=channel, text=text))
            self._messages.setdefault(session_id, []).append({"role": "user", "content": text})
            return list(turns)

    def record_reply(self, session_id: str, text: str, privacy: Privacy = Privacy.PUBLIC) -> None:
        with self._lock:
            self._messages.setdefault(session_id, []).append({"role": "assistant", "content": text})
            self._privacy[session_id] = self.reply_privacy(session_id, privacy)

    def messages(self, session_id: str) -> list[dict[str, str]]:
        with self._lock:
            # Bound inference context independently of the historical turn counter.
            return [dict(message) for message in self._messages.get(session_id, [])[-39:]]

    def previous_user_message(self, session_id: str) -> str | None:
        """The user turn immediately before the current one — used only by
        Phase 24a's referential-inclusion heuristic (companion_core.websearch.
        policy). `append` has already recorded the current turn as the last
        "user" entry by the time the generic branch calls this, so the
        second-to-last user entry is the prior turn, never the current one."""
        with self._lock:
            user_texts = [m["content"] for m in self._messages.get(session_id, []) if m["role"] == "user"]
            return user_texts[-2] if len(user_texts) >= 2 else None

    def turn_lock(self, session_id: str) -> asyncio.Lock:
        # A model call yields for seconds; serialize same-session turns so two
        # channels cannot interleave user messages and attach replies out of order.
        return self._session_locks.setdefault(session_id, asyncio.Lock())

    def reply_privacy(self, session_id: str, current: Privacy) -> Privacy:
        # Generated replies can repeat earlier calendar/email/memory content.
        # Keep the strongest label for this in-memory conversation rather than
        # silently treating a follow-up such as "tell me more" as public.
        rank = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}
        return max(current, self._privacy.get(session_id, Privacy.PUBLIC), key=rank.__getitem__)
