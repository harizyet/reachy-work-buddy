"""Is a transcribed wake candidate a turn addressed to Reachy? (Phase 24g,
ADR 0023 wake-started sessions)

Fixed, deterministic rules; no model decides, and nothing here grants a
permission or identifies anyone. Ambiguous candidates are rejected: a
wrongly rejected wake costs the speaker a repeat, while a wrongly admitted
one starts a conversation nobody asked for.

The robot uploads the wake phrase together with the request, so the
transcript must itself confirm the phrase near its start. STT is biased
towards the robot's name by its initial prompt, but 24d still heard it as
"Ricci"/"Richi", so close spellings count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAMES = frozenset(
    {
        "reachy", "reachie", "reachi", "reechy", "reechie", "richie", "richi",
        "ritchie", "ricci", "ritchy", "ritchi", "reaches", "reachey",
    }
)  # fmt: skip
# The name must fall within the first few words ("Hey Reachy", "Okay hey
# Reachy"); later, it is more likely talk about the robot than to it.
_NAME_WITHIN = 3
_FILLERS = frozenset(
    {
        "um", "uh", "er", "erm", "hmm", "hm", "mm", "mhm", "ah", "oh", "eh",
        "huh", "ok", "okay", "so", "well", "yeah", "hey", "hi", "hello",
    }
)  # fmt: skip
# A request opening like this continues someone else's sentence rather than
# starting one addressed to the robot.
_CONTINUATION_OPENERS = frozenset({"and", "but", "then", "or", "because"})
_WORD = re.compile(r"[a-z']+")


@dataclass(frozen=True)
class Relevance:
    admitted: bool
    reason: str
    # The request with the wake phrase removed; empty when rejected.
    request: str = ""


def assess(transcript: str) -> Relevance:
    words = list(_WORD.finditer(transcript.lower()))
    if not words:
        return Relevance(False, "no_speech")
    name_index = next(
        (i for i, match in enumerate(words[:_NAME_WITHIN]) if match.group() in _NAMES),
        None,
    )
    if name_index is None:
        return Relevance(False, "no_wake_phrase")
    rest = words[name_index + 1 :]
    if not rest:
        return Relevance(False, "no_request")
    if all(match.group() in _FILLERS for match in rest):
        return Relevance(False, "filler_only")
    if rest[0].group() in _CONTINUATION_OPENERS:
        return Relevance(False, "continuation")
    request = transcript[rest[0].start() :].strip()
    return Relevance(True, "admitted", request[:1].upper() + request[1:])
