"""In-memory per-session transcript.

Not durable, not real memory — Phase 12 (work memory) replaces this with a
MemoryRecord-backed store (provenance, sensitivity, expiry). This exists
only so companion-core can be genuinely channel-agnostic per docs/adr/0002
and demonstrate shared conversation state across channels (Phase 5's exit
criterion) without pulling in a database this phase doesn't need.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class Turn:
    channel: str
    text: str


class ConversationStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[str, list[Turn]] = {}

    def append(self, session_id: str, channel: str, text: str) -> list[Turn]:
        with self._lock:
            turns = self._turns.setdefault(session_id, [])
            turns.append(Turn(channel=channel, text=text))
            return list(turns)
