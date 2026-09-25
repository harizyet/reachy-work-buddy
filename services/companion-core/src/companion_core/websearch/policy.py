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
    "tomorrow", "tonight", "forecast",
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
    "he", "she", "him", "her", "his", "their", "there",
)
_QUERY_CHAR_LIMIT = 300
_WEATHER_RE = re.compile(r"\b(weather|forecast|temperature|rain|raining|humid|humidity)\b")


def matches_auto_heuristic(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _SEARCH_PHRASES):
        return True
    if _FRESHNESS_WORD_RE.search(lowered):
        return True
    return bool(_YEAR_RE.search(text))


def should_search(text: str, *, policy: SearchPolicy, follows_search: bool = False) -> bool:
    """`follows_search`: the immediately preceding user turn searched. Under
    Auto, a follow-up to it ("When was it released?", "What about
    tomorrow?") searches too, though it has no freshness word of its own."""
    if policy == SearchPolicy.ALWAYS:
        return True
    if policy == SearchPolicy.AUTO:
        return matches_auto_heuristic(text) or (follows_search and is_follow_up(text))
    return False


def is_follow_up(text: str) -> bool:
    """Narrower than _is_referential: a bare short reply ("thanks", "ok")
    must not trigger a search, so short turns count only as questions."""
    lowered = text.strip().lower()
    words = re.findall(r"[\w']+", lowered)
    if not words:
        return False
    if len(words) <= _REFERENTIAL_WORD_LIMIT and lowered.endswith("?"):
        return True
    return _has_referential_cue(lowered, set(words))


def _has_referential_cue(lowered: str, wordset: set[str]) -> bool:
    for cue in _REFERENTIAL_CUES:
        if " " in cue:
            if cue in lowered:
                return True
        elif cue in wordset:
            return True
    return False


def _is_referential(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    words = re.findall(r"[\w']+", lowered)
    if len(words) <= _REFERENTIAL_WORD_LIMIT:
        return True
    return _has_referential_cue(lowered, set(words))


def build_query(
    current_turn: str, previous_user_turn: str | None, *, search_topic: str | None = None
) -> str:
    """Fixed rules only — never LLM-rewritten. A referential turn is
    prefixed with context: the search topic (the query the thread's last
    self-contained search already sent, so nothing new from the
    conversation reaches the provider) when the previous turn searched.
    Otherwise the immediately preceding user turn is added only for an
    explicit reference ("it", "what about"): a short self-contained question
    ("What's the weather today?") must not carry an unrelated prior turn.
    The current turn is never truncated away."""
    current = current_turn.strip()[:_QUERY_CHAR_LIMIT]
    if search_topic:
        context = search_topic if _is_referential(current) else None
    else:
        lowered = current.lower()
        cue = _has_referential_cue(lowered, set(re.findall(r"[\w']+", lowered)))
        context = previous_user_turn if cue else None
    if not context:
        return current
    room = _QUERY_CHAR_LIMIT - len(current) - 1
    return f"{context.strip()[:room]} {current}" if room > 0 else current


def next_search_topic(current_turn: str, query: str, search_topic: str | None) -> str:
    """A follow-up keeps its thread's topic so chained follow-ups ("When was
    it released?" then "Any news about it?") don't lose the subject."""
    return search_topic if search_topic and _is_referential(current_turn.strip()) else query


def localize_query(query: str, location: str | None) -> str:
    """Weather without a place means the owner's own location. Sending that
    location to the search provider is disclosed in the operator UI."""
    if not location or not _WEATHER_RE.search(query.lower()) or location.lower() in query.lower():
        return query
    return f"{query} in {location}"
