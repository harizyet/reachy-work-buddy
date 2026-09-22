"""Placeholder intent detection for memory capture/recall — same honesty-
about-scope as task_intent.py and calendar_intent.py: prefix/phrase
matchers, not real NLU. Phase 12's exit criterion ("Stored work fact can be
recalled later without transcript dumping") needs the store/recall to be
genuinely backed by MemoryStore, not that the language understanding be
sophisticated.
"""

from __future__ import annotations

from shared.models.memory import MemoryRecord
from shared.models.response import Privacy

_PRIVACY_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}

_CAPTURE_PREFIXES = ("remember that ", "please remember that ", "remember ")
_RECALL_PREFIXES = ("what do you remember about ", "do you remember ", "recall ")


def _match_prefix(text: str, prefixes: tuple[str, ...]) -> str | None:
    lowered = text.strip().lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text.strip()[len(prefix) :].strip()
    return None


def match_capture(text: str) -> str | None:
    return _match_prefix(text, _CAPTURE_PREFIXES) or None


def match_recall(text: str) -> str | None:
    return _match_prefix(text, _RECALL_PREFIXES) or None


def format_capture_reply(record: MemoryRecord) -> str:
    return f"I'll remember that: {record.content}."


def format_recall_reply(records: list[MemoryRecord], query: str) -> str:
    if not records:
        return f"I don't have anything stored about '{query}'."
    lines = "; ".join(r.content for r in records)
    return f"Here's what I remember: {lines}."


def most_restrictive_privacy(records: list[MemoryRecord], default: Privacy = Privacy.PUBLIC) -> Privacy:
    """A recall reply combining several records is only as safe to speak
    aloud as its most restrictive member — revealing one sensitive fact
    alongside three public ones still reveals the sensitive one."""
    if not records:
        return default
    return max((r.sensitivity for r in records), key=lambda p: _PRIVACY_RANK[p])
