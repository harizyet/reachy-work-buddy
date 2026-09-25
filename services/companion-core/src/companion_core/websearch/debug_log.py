"""Owner debug view of recent searches (Phase 24a follow-up). Deliberately in memory
only: queries are drawn from user turns, so they are never persisted and a
restart clears them. Bounded so it can't grow with conversation volume."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime

from companion_core.websearch.provider import SearchResult

MAX_ENTRIES = 50


@dataclass(frozen=True)
class SearchAttempt:
    provider: str
    # ok, error, limit_reported (provider said its plan limit is reached),
    # at_limit (skipped, Reachy's own monthly count reached), timeout.
    outcome: str
    ms: int


@dataclass(frozen=True)
class SearchLogEntry:
    at: datetime
    query: str
    policy: str
    served_by: str | None
    total_ms: int
    attempts: list[SearchAttempt] = field(default_factory=list)
    results: list[SearchResult] = field(default_factory=list)


class SearchDebugLog:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._entries: deque[SearchLogEntry] = deque(maxlen=max_entries)

    def record(self, entry: SearchLogEntry) -> None:
        self._entries.append(entry)

    def entries(self) -> list[dict]:
        return [
            {**asdict(entry), "at": entry.at.isoformat()}
            for entry in reversed(self._entries)
        ]
