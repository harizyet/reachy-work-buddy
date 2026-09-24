"""Deterministic search-trigger and query-scope heuristics for Phase 24a —
same placeholder-matcher honesty as the *_intent.py modules: fixed
keyword/pattern rules, never an LLM classifier. The model has no authority
to request, skip, or suppress a search; only this module decides. See
docs/phase-24a.md's "Required behaviour" section for the exact rules this
implements.
"""

from __future__ import annotations

import re

from shared.models.websearch import SearchPolicy

_SEARCH_PHRASES = ("search for ", "look this up", "check online", "look up ")
_FRESHNESS_WORDS = (
    "latest", "current", "today", "recent", "this week", "now",
    "release", "version", "price", "weather", "news",
)
_YEAR_RE = re.compile(r"\b20[2-9]\d\b")
_FRESHNESS_WORD_RE = re.compile(
    "|".join(rf"\b{re.escape(word)}\b" for word in _FRESHNESS_WORDS)
)

# A short, referential-looking follow-up ("How much does it cost?") pulls in
# the immediately preceding user turn; a self-contained question of similar
# length ("What's the latest CUDA version?") must not, so the length cutoff
# alone stays low — the cue list carries the rest of the referential cases.
_REFERENTIAL_WORD_LIMIT = 4
_REFERENTIAL_CUES = (
    "it", "that", "those", "they", "them", "this", "how much", "when was it",
    "what about", "compared to", "is it", "does it",
)
_QUERY_CHAR_LIMIT = 300


def matches_auto_heuristic(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _SEARCH_PHRASES):
        return True
    if _FRESHNESS_WORD_RE.search(lowered):
        return True
    return bool(_YEAR_RE.search(text))


def should_search(text: str, *, policy: SearchPolicy) -> bool:
    if policy == SearchPolicy.ALWAYS:
        return True
    if policy == SearchPolicy.AUTO:
        return matches_auto_heuristic(text)
    return False


def _is_referential(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    words = re.findall(r"[\w']+", lowered)
    if len(words) <= _REFERENTIAL_WORD_LIMIT:
        return True
    wordset = set(words)
    for cue in _REFERENTIAL_CUES:
        if " " in cue:
            if cue in lowered:
                return True
        elif cue in wordset:
            return True
    return False


def build_query(current_turn: str, previous_user_turn: str | None) -> str:
    """Fixed rules only — never LLM-rewritten. Includes the immediately
    preceding user turn only when the current turn looks referential on its
    own; a self-contained turn never pulls in an unrelated prior message."""
    current = current_turn.strip()
    if previous_user_turn and _is_referential(current):
        query = f"{previous_user_turn.strip()} {current}"
    else:
        query = current
    return query[:_QUERY_CHAR_LIMIT]
