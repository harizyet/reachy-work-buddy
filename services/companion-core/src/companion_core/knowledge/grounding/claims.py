"""C4: atomic-claim generation. The model is asked for JSON: a list of claims, each with exactly ONE evidence id and a verbatim quote from that item, plus an `unknown` list for what it cannot establish.
Rendering to prose is deterministic. The schema forbids empty quotes (`minLength`), but a schema is only a request: C5 (validate.py) is what decides whether any claim counts."""

from __future__ import annotations

import json
from collections.abc import Sequence

QUOTE_MIN_CHARS = 12
SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "claim": {"type": "string", "minLength": 8, "maxLength": 240},
            "evidence": {"type": "string", "pattern": "^E[0-9]+$"},
            "quote": {"type": "string", "minLength": QUOTE_MIN_CHARS, "maxLength": 300}},
            "required": ["claim", "evidence", "quote"], "additionalProperties": False}},
        "unknown": {"type": "array", "items": {"type": "string", "minLength": 3, "maxLength": 160}},
    },
    "required": ["claims", "unknown"], "additionalProperties": False,
}
INSTRUCTION = (
    "Answer ONLY with JSON of the form {\"claims\": [...], \"unknown\": [...]}. Each claim is one fact with exactly one evidence id (like E2) and a quote copied exactly, word for word, from that "
    "evidence item (at least a few words that contain the fact). Never combine facts from different items in one claim. If the evidence does not establish something the question asks, put a short "
    "description of it in \"unknown\" instead of guessing. If nothing is established, return an empty claims list."
)


def with_instruction(messages: Sequence[dict]) -> list[dict]:
    out = list(messages)
    out.insert(len(out) - 1, {"role": "system", "content": INSTRUCTION})
    return out


def parse(text: str) -> tuple[list[dict], list[str]] | None:
    """(claims, unknown) or None when the output is not the requested JSON. Anything else is treated as no answer, never as prose to show."""
    try:
        data = json.loads(text)
        claims = data["claims"]
        unknown = data["unknown"]
        if not isinstance(claims, list) or not isinstance(unknown, list):
            return None
        return [c for c in claims if isinstance(c, dict)], [str(u) for u in unknown]
    except (ValueError, KeyError, TypeError):
        return None


def render(accepted: Sequence[dict], unknown: Sequence[str], dropped: int) -> str:
    """Deterministic prose from the ACCEPTED claims only; nothing the model wrote outside a validated claim or the unknown list is shown."""
    parts = [f"{c['claim'].rstrip('.')} [{c['evidence']}]." for c in accepted]
    if unknown or dropped or not accepted:
        what = "; ".join(u.rstrip(".") for u in unknown) if unknown else "the rest of what you asked"
        parts.append(f"I don't have a record that establishes: {what}.")
    return " ".join(parts)
