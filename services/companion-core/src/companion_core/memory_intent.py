"""Placeholder intent detection for memory capture/recall — same honesty-
about-scope as task_intent.py and calendar_intent.py: prefix/phrase
matchers, not real NLU. Phase 12's exit criterion ("Stored work fact can be
recalled later without transcript dumping") needs the store/recall to be
genuinely backed by MemoryStore, not that the language understanding be
sophisticated.

forget/confirm-forget/restore matchers (docs/adr/0011): forgetting a
memory is this codebase's first destructive action, and it's gated behind
companion_core.consent — "forget X" only *requests* a confirmation, "yes
forget X" is what actually confirms it (and is refused if it arrives as
voice), and "restore X" undoes an already-forgotten one.

_match_prefix strips commas and trailing sentence punctuation before
matching — discovered live-testing the voice-confirmation block through
the real STT pipeline: faster-whisper transcribed spoken "yes forget
Alice" as "Yes, forget Alice.", and a literal prefix match rejected it
outright (comma right after "Yes"), which would have looked like the
matcher just not firing rather than the voice check running at all. Not
a security issue on its own — no destructive path exists without a match
— but it made the confirmation phrase impossible to ever say out loud
successfully, voice or not.
"""

from __future__ import annotations

from shared.models.memory import MemoryRecord
from shared.models.response import Privacy

_PRIVACY_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}

_CAPTURE_PREFIXES = ("remember that ", "please remember that ", "remember ")
_RECALL_PREFIXES = ("what do you remember about ", "do you remember ", "recall ")
_CONFIRM_FORGET_PREFIXES = ("yes forget ", "confirm forget ")
_FORGET_PREFIXES = ("forget that ", "forget ", "delete memory about ")
_RESTORE_PREFIXES = ("restore ", "undo forget ", "unforget ")

_TRAILING_PUNCTUATION = ".,!?"


def _match_prefix(text: str, prefixes: tuple[str, ...]) -> str | None:
    normalized = text.strip().replace(",", "")
    lowered = normalized.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            remainder = normalized[len(prefix) :].strip().rstrip(_TRAILING_PUNCTUATION).strip()
            return remainder or None
    return None


def match_capture(text: str) -> str | None:
    return _match_prefix(text, _CAPTURE_PREFIXES) or None


def match_recall(text: str) -> str | None:
    return _match_prefix(text, _RECALL_PREFIXES) or None


def match_confirm_forget(text: str) -> str | None:
    return _match_prefix(text, _CONFIRM_FORGET_PREFIXES) or None


def match_forget(text: str) -> str | None:
    return _match_prefix(text, _FORGET_PREFIXES) or None


def match_restore(text: str) -> str | None:
    return _match_prefix(text, _RESTORE_PREFIXES) or None


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


def format_forget_not_found_reply(query: str) -> str:
    return f"I don't have anything stored matching '{query}' to forget."


def format_forget_confirmation_reply(record: MemoryRecord, query: str) -> str:
    return f'To permanently forget "{record.content}", say: yes forget {query}'


def format_forgotten_reply(record: MemoryRecord) -> str:
    return f'Forgotten: "{record.content}". Say "restore {record.content[:20]}" if you change your mind.'


def format_confirmation_not_found_reply(query: str) -> str:
    return f"I couldn't find a pending forget request matching '{query}' — it may have expired. Try again."


def format_voice_confirmation_blocked_reply() -> str:
    return "For your security, I can't accept that confirmation by voice. Please confirm from a text channel like Telegram."


def format_restore_not_found_reply(query: str) -> str:
    return f"I don't have anything forgotten matching '{query}' to restore."


def format_restored_reply(record: MemoryRecord) -> str:
    return f'Restored: "{record.content}".'
