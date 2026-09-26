"""Deterministic search-trigger and query-scope heuristics for Phase 24a —
same placeholder-matcher honesty as the *_intent.py modules: fixed
keyword/pattern rules, never an LLM classifier. The model has no authority
to request, skip, or suppress a search; only this module decides. See
docs/phase-24a.md's "Required behaviour" section for the exact rules this
implements, and docs/phase-24e.md scope item 2 for the 24d misfire fixes.
"""

from __future__ import annotations

import re

from shared.models.websearch import SearchPolicy

_SEARCH_PHRASES = ("search for ", "look this up", "check online", "look up ")
# "now" alone is not a cue (Phase 24e): "Goodbye for now." searched in 24d.
# It still counts inside the phrases in _FRESHNESS_PHRASE_RE.
_FRESHNESS_WORDS = (
    "latest", "current", "today", "recent", "this week",
    "release", "version", "price", "weather", "news",
    "tomorrow", "tonight", "forecast",
)
_YEAR_RE = re.compile(r"\b20[2-9]\d\b")
_FRESHNESS_WORD_RE = re.compile(
    "|".join(rf"\b{re.escape(word)}\b" for word in _FRESHNESS_WORDS)
)
_FRESHNESS_PHRASE_RE = re.compile(r"\b(?:right now in|open now|now open|as of now)\b")

# Closings, greetings and thanks. A turn is social only when nothing but
# these phrases and _SOCIAL_FILLER remains, so "Thanks, what's the weather
# today?" still searches.
_SOCIAL_RE = re.compile(
    r"\b(?:good ?bye|bye(?: bye)?|see (?:you|ya)|talk (?:to you )?(?:later|soon)|good ?night"
    r"|thank you|thanks|cheers|hello|hi|hey|hiya|good (?:morning|afternoon|evening)"
    r"|how are you|how's it going|nice to meet you|that's all)\b"
)
_SOCIAL_FILLER = frozenset({
    "for", "now", "then", "again", "so", "much", "very", "a", "lot", "you", "too",
    "reachy", "all", "later", "soon", "tomorrow", "tonight", "today", "oh", "well",
    "ok", "okay", "and", "everyone", "there", "buddy", "doing", "it", "is",
})
# The whole turn must be the question, so "What can you do about the
# latest news?" is not self-identity.
_SELF_IDENTITY_RE = re.compile(
    r"(?:(?:hey|hi|hello|so|and|ok|okay|well|oh|reachy) )*"
    r"(?:who are you|what are you|who am i talking to|what(?:'s| is) your name"
    r"|what (?:else )?can you do|what are you able to do|what do you do|how do you work"
    r"|tell me about yourself|introduce yourself|are you a robot)"
    r"(?: (?:reachy|again|exactly|anyway|then|for me))*"
)

# A follow-up must point back at the previous search's subject. "there",
# "how much" and statements are not enough on their own (24d merged
# unrelated fragments that way).
_REFERENTIAL_WORD_LIMIT = 4
_FOLLOW_UP_OPENERS = ("what about", "how about", "compared to", "tell me more", "more about")
_BACK_REFERENCES = frozenset({
    "it", "its", "that", "those", "this", "these", "they", "them", "their",
    "he", "she", "him", "her", "his",
})
_QUESTION_STARTS = frozenset({
    "what", "what's", "when", "where", "who", "whose", "why", "how", "which",
    "is", "are", "was", "were", "do", "does", "did", "can", "could", "will",
    "would", "should", "has", "have", "any",
})
# Requests for information, for turns that are not phrased as questions.
_LEADING_FILLER = frozenset({"hey", "hi", "hello", "ok", "okay", "so", "and", "well", "reachy", "please", "um", "uh"})
_QUESTION_WORDS = frozenset({"what", "what's", "when", "where", "which", "who", "whose", "why", "how", "how's"})
_REQUEST_PHRASE_RE = re.compile(
    r"\b(?:tell me|show me|give me|let me know|i want to know|i'd like to know|i wonder"
    r"|find out|check|any news|remind me what)\b"
)
_TERSE_QUERY_WORDS = 3
_QUERY_CHAR_LIMIT = 300
_WEATHER_RE = re.compile(r"\b(weather|forecast|temperature|rain|raining|humid|humidity)\b")


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[\w']+", text.lower()))


def matches_auto_heuristic(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _SEARCH_PHRASES):
        return True
    fresh = (
        _FRESHNESS_WORD_RE.search(lowered) or _FRESHNESS_PHRASE_RE.search(_normalize(text))
        or _YEAR_RE.search(text)
    )
    return bool(fresh) and _is_request(text)


def _is_request(text: str) -> bool:
    """A question, a request phrase or a terse query ("Weather today."). A
    plain statement ("I'm feeling tired today.") is not, whatever its
    freshness words (Phase 24e). STT often drops the question mark, so a
    question word anywhere counts too."""
    words = _normalize(text).split()
    while words and words[0] in _LEADING_FILLER:
        words = words[1:]
    if not words:
        return False
    return (
        text.strip().endswith("?")
        or words[0] in _QUESTION_STARTS
        or not _QUESTION_WORDS.isdisjoint(words)
        or _REQUEST_PHRASE_RE.search(" ".join(words)) is not None
        or len(words) <= _TERSE_QUERY_WORDS
    )


def is_social(text: str) -> bool:
    normalized = _normalize(text)
    remainder = _SOCIAL_RE.sub(" ", normalized)
    return remainder != normalized and set(remainder.split()) <= _SOCIAL_FILLER


def is_self_identity(text: str) -> bool:
    return _SELF_IDENTITY_RE.fullmatch(_normalize(text)) is not None


def should_search(text: str, *, policy: SearchPolicy, follows_search: bool = False) -> bool:
    """`follows_search`: the immediately preceding user turn searched. Under
    Auto, a follow-up to it ("When was it released?", "What about
    tomorrow?") searches too, though it has no freshness word of its own.
    Closings, greetings, thanks and self-identity questions never search
    under Auto; Always still searches every turn."""
    if policy == SearchPolicy.ALWAYS:
        return True
    if policy == SearchPolicy.AUTO:
        if is_social(text) or is_self_identity(text):
            return False
        return matches_auto_heuristic(text) or (follows_search and is_follow_up(text))
    return False


def is_follow_up(text: str) -> bool:
    return _refers_back(text, allow_short=True)


def _refers_back(text: str, *, allow_short: bool) -> bool:
    """Opener phrases ("what about Tuesday?") always refer back. Otherwise
    the turn must be a question and either use a back-reference pronoun or,
    with `allow_short`, be a short question with no freshness subject of its
    own ("Why?"), so "What's the weather today?" is self-contained."""
    lowered = text.strip().lower()
    words = re.findall(r"[\w']+", lowered)
    if not words or is_social(text) or is_self_identity(text):
        return False
    if any(opener in lowered for opener in _FOLLOW_UP_OPENERS):
        return True
    if not (lowered.endswith("?") or words[0] in _QUESTION_STARTS):
        return False
    # "And tomorrow?" continues the thread; "and she said…" is not a question.
    if (words[0] == "and" and len(words) > 1) or _BACK_REFERENCES.intersection(words):
        return True
    return allow_short and len(words) <= _REFERENTIAL_WORD_LIMIT and not matches_auto_heuristic(text)


def build_query(
    current_turn: str, previous_user_turn: str | None, *, search_topic: str | None = None
) -> str:
    """Fixed rules only — never LLM-rewritten. A follow-up (is_follow_up) is
    prefixed with context: the search topic (the query the thread's last
    self-contained search already sent, so nothing new from the
    conversation reaches the provider) when the previous turn searched.
    Otherwise the immediately preceding user turn is added only for an
    explicit reference ("it", "what about"): a short self-contained question
    ("What's the weather today?") must not carry an unrelated prior turn.
    The current turn is never truncated away."""
    current = current_turn.strip()[:_QUERY_CHAR_LIMIT]
    if search_topic:
        context = search_topic if is_follow_up(current) else None
    else:
        context = previous_user_turn if _refers_back(current, allow_short=False) else None
    if not context:
        return current
    room = _QUERY_CHAR_LIMIT - len(current) - 1
    return f"{context.strip()[:room]} {current}" if room > 0 else current


def next_search_topic(current_turn: str, query: str, search_topic: str | None) -> str:
    """A follow-up keeps its thread's topic so chained follow-ups ("When was
    it released?" then "Any news about it?") don't lose the subject."""
    return search_topic if search_topic and is_follow_up(current_turn.strip()) else query


# A named place after a preposition, e.g. "in Jakarta". STT and typed text
# capitalize place names; "in the morning" stays unmatched.
_NAMED_PLACE_RE = re.compile(r"\b(?:in|at|for|near|around)\s+[A-Z][\w'-]+")


def localize_query(query: str, location: str | None) -> str:
    """Weather without a place means the owner's own location. Sending that
    location to the search provider is disclosed in the operator UI. A
    question that names its own place keeps it: the 24e physical run sent
    "What's the weather in Jakarta today? in Singapore"."""
    if (
        not location
        or not _WEATHER_RE.search(query.lower())
        or location.lower() in query.lower()
        or _NAMED_PLACE_RE.search(query)
    ):
        return query
    return f"{query} in {location}"
