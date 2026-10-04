"""Spoken "that's all" at the end of a live robot conversation.

Fixed, deterministic phrases and only when they are the whole utterance, so
"thank you, what's the weather" is still a question. It only ends the voice
session; it never authorizes an action.
"""

from __future__ import annotations

import re

_LEAD = ("ok", "okay", "alright", "all right", "no", "yes", "well", "hey", "reachy", "reachey", "richie", "right")
_CORE = (
    "thank you", "thanks", "thank you very much", "thanks a lot", "thank you so much", "thanks so much",
    "that's all", "that is all", "that will be all", "that'll be all", "that's it", "that is it", "that's everything",
    "goodbye", "good bye", "bye", "bye bye", "see you", "see you later", "good night",
)  # fmt: skip
_TRAIL = ("reachy", "reachey", "richie", "for now", "for today", "thanks", "thank you", "bye", "goodbye", "very much")


def _alt(words: tuple[str, ...]) -> str:
    return "|".join(map(re.escape, sorted(words, key=len, reverse=True)))


_PATTERN = re.compile(rf"^(?:(?:{_alt(_LEAD)})\s+)*(?:{_alt(_CORE)})(?:\s+(?:{_alt(_TRAIL)}))*$")


def matches_end_conversation(transcript: str) -> bool:
    text = " ".join(re.sub(r"[^a-z' ]+", " ", transcript.lower()).split())
    return bool(_PATTERN.match(text))
