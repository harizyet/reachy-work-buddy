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

# Messages the model sees per turn. A carried privacy label expires once
# the message it came from has left this window: nothing private can then
# be repeated, so it no longer needs to silence the robot.
CONTEXT_MESSAGES = 39

_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}


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
        # session -> [(index in _messages of the reply it came with, label)]
        self._private_marks: dict[str, list[tuple[int, Privacy]]] = {}
        self._messages: dict[str, list[dict[str, str]]] = {}
        # session -> (search topic, number of user turns when it was set)
        self._search_topics: dict[str, tuple[str, int]] = {}

    def clear(self) -> None:
        """Remove provider-derived context when an account connection is removed."""
        with self._lock:
            self.generation += 1
            self._turns.clear()
            self._messages.clear()
            self._private_marks.clear()
            self._search_topics.clear()

    def append(self, session_id: str, channel: str, text: str) -> list[Turn]:
        with self._lock:
            turns = self._turns.setdefault(session_id, [])
            turns.append(Turn(channel=channel, text=text))
            self._messages.setdefault(session_id, []).append({"role": "user", "content": text})
            return list(turns)

    def record_reply(
        self, session_id: str, text: str, privacy: Privacy = Privacy.PUBLIC, *, carried: Privacy | None = None
    ) -> None:
        """`privacy` labels this reply; `carried` (default: the same) is what
        later replies in the conversation inherit. They differ for generated
        replies: a keyword in the model's own wording labels only that reply,
        while private data (tool results, the owner's own sensitive
        statements) stays in history and must keep later replies private."""
        label = privacy if carried is None else carried
        with self._lock:
            messages = self._messages.setdefault(session_id, [])
            messages.append({"role": "assistant", "content": text})
            if label != Privacy.PUBLIC:
                # Marked at the reply, the later of the two messages, since
                # private tool results live in the reply.
                self._private_marks.setdefault(session_id, []).append((len(messages) - 1, label))

    def messages(self, session_id: str) -> list[dict[str, str]]:
        with self._lock:
            # Bound inference context independently of the historical turn counter.
            return [dict(message) for message in self._messages.get(session_id, [])[-CONTEXT_MESSAGES:]]

    def previous_user_message(self, session_id: str) -> str | None:
        """The user turn immediately before the current one — used only by
        Phase 24a's referential-inclusion heuristic (companion_core.websearch.
        policy). `append` has already recorded the current turn as the last
        "user" entry by the time the generic branch calls this, so the
        second-to-last user entry is the prior turn, never the current one."""
        with self._lock:
            user_texts = [m["content"] for m in self._messages.get(session_id, []) if m["role"] == "user"]
            return user_texts[-2] if len(user_texts) >= 2 else None

    def _user_turns(self, session_id: str) -> int:
        return sum(1 for m in self._messages.get(session_id, []) if m["role"] == "user")

    def search_topic(self, session_id: str) -> str | None:
        """The topic set by the immediately preceding user turn's search, or
        None when that turn didn't search (any non-search turn ends the
        thread, including deterministic intents)."""
        with self._lock:
            topic = self._search_topics.get(session_id)
            if topic is None or topic[1] != self._user_turns(session_id) - 1:
                return None
            return topic[0]

    def set_search_topic(self, session_id: str, topic: str) -> None:
        with self._lock:
            self._search_topics[session_id] = (topic, self._user_turns(session_id))

    def turn_lock(self, session_id: str) -> asyncio.Lock:
        # A model call yields for seconds; serialize same-session turns so two
        # channels cannot interleave user messages and attach replies out of order.
        return self._session_locks.setdefault(session_id, asyncio.Lock())

    def reply_privacy(self, session_id: str, current: Privacy) -> Privacy:
        """Generated replies can repeat earlier calendar/email/memory
        content, so a follow-up such as "tell me more" keeps the strongest
        label still in the model's context. Owner decision (2026-09-26, 24e
        physical run): it expires once that message has left the context,
        rather than silencing the robot for the rest of the conversation."""
        with self._lock:
            window_start = max(0, len(self._messages.get(session_id, [])) - CONTEXT_MESSAGES)
            marks = [m for m in self._private_marks.get(session_id, []) if m[0] >= window_start]
            self._private_marks[session_id] = marks
        return max([current, *(label for _, label in marks)], key=_RANK.__getitem__)
