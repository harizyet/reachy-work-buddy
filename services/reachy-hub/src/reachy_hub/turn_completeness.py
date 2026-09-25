"""Does a transcribed voice segment sound finished? (Phase 24e, ADR 0023)

Fixed, deterministic heuristics; no model decides. A wrong "unfinished"
costs the continuation window in latency, while a wrong "finished" splits
the turn as before, so the rules lean towards holding only on endings that
rarely close an English sentence.

STT punctuation is unreliable in both directions: faster-whisper adds a
final period to most segments, including ones the speaker trailed off, and
omits punctuation from some finished ones. So a period never overrides an
unfinished ending, and a missing one never makes a segment unfinished.
"""

from __future__ import annotations

import re

# Endings that almost never close a sentence, whatever punctuation STT
# added: articles, possessives, conjunctions and fillers.
_UNFINISHED_WORDS = frozenset(
    {
        "a", "an", "the", "my", "your", "our", "their", "his", "its",
        "and", "or", "but", "nor", "because", "cause", "if", "unless",
        "although", "whereas", "whether", "until", "than", "very",
        "um", "uh", "er", "erm",
    }
)  # fmt: skip

# Prepositions that are rarely phrasal-verb particles ("on", "in", "up" and
# "off" are left out: "turn it on" is finished). A question may end on one
# ("Who are you talking to?"), so a question mark keeps these complete.
_PREPOSITIONS = frozenset(
    {
        "about", "with", "to", "for", "of", "from", "at", "into", "onto",
        "by", "like", "as", "between", "without", "towards", "toward",
    }
)  # fmt: skip

# Short phrases that introduce what the speaker is about to say.
_UNFINISHED_PHRASES = (
    ("tell", "me"),
    ("show", "me"),
    ("i", "was", "wondering"),
    ("i", "wonder"),
    ("i", "think"),
    ("the", "thing", "is"),
)

_TRAILING_UNFINISHED_MARKS = (",", ":", ";", "-", "–", "—")
_WORD = re.compile(r"[a-z']+")


def looks_complete(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.endswith(("...", "…")) or stripped.endswith(_TRAILING_UNFINISHED_MARKS):
        return False
    words = _WORD.findall(stripped.lower())
    if not words:
        return True
    last = words[-1]
    if last in _UNFINISHED_WORDS:
        return False
    if any(tuple(words[-len(phrase) :]) == phrase for phrase in _UNFINISHED_PHRASES):
        return False
    if last in _PREPOSITIONS:
        return stripped.endswith("?")
    return True
