"""Spoken "privacy mode on" request in a live robot conversation.

Fixed, deterministic phrases; no model decides. This only ever *restricts*
the robot (it stops listening for the wake phrase), so a spoken request is
honoured. Turning privacy mode off is never spoken: the robot is not
listening then, and it needs an authenticated channel (Telegram `/privacy
off` or the operator UI).
"""

from __future__ import annotations

import re

_LEAD = (
    "hey", "ok", "okay", "please", "reachy", "reachey", "richie", "could you", "can you", "would you",
    "i want you to", "lets", "let's", "go into", "go in", "go to", "switch to", "switch into", "turn on",
    "turn", "enable", "activate", "start", "enter", "set", "put yourself in", "put yourself into",
)  # fmt: skip
_TRAIL = ("on", "please", "now", "for me")
_PATTERN = re.compile(
    rf"^(?:(?:{'|'.join(map(re.escape, _LEAD))})\s+)*privacy mode(?:\s+(?:{'|'.join(map(re.escape, _TRAIL))}))*$"
)


def matches_privacy_on(transcript: str) -> bool:
    text = " ".join(re.sub(r"[^a-z' ]+", " ", transcript.lower()).split())
    return bool(_PATTERN.match(text))
