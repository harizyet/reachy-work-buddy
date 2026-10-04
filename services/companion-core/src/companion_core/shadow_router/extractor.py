"""Few-shot argument extractor (shadow only). Uses the LOCAL provider exclusively: utterances are never sent to a cloud model for this.
The output is untrusted: it is only ever passed to validator.validate()."""
from __future__ import annotations

import json

import httpx

from companion_core.shadow_router.validator import SCHEMAS
from shared.models.llm import ProviderConfig

_DESC = {
    "to": "recipient exactly as named in the utterance (name, role, or address); null if none is named",
    "topic": "what the message is about, copied/trimmed from the utterance; null if not stated",
    "title": "the task text, copied/trimmed from the utterance; null if not stated",
    "due": "when it is due, exactly as stated; null if no time is stated",
    "task": "which existing task is meant, as stated; null if the utterance gives no way to tell (e.g. 'it', 'that one')",
    "content": "the fact to store, copied/trimmed from the utterance; null if nothing is stated",
    "query": "what to look up/forget, copied/trimmed from the utterance; null if none is given",
    "scope": "'bulk' if the user asks to forget everything / all notes / the whole memory, otherwise 'single'",
    "when": "the date/time expression as stated (e.g. 'Thursday afternoon'); null if none stated",
    "sender": "who the email is from, as named; null if none named",
    "place": "the city/place if one is named; null for local time",
}
_HEAD = (
    "You extract arguments from ONE user utterance for a home-assistant action. Output ONLY a JSON object with exactly the requested keys. "
    "Copy values from the utterance (trim filler words); NEVER invent, guess, or resolve references ('it', 'that one'); use null when a value is not stated."
)
_FEW = [
    ("tasks.capture", "add ring the dentist to my list for monday", {"title": "ring the dentist", "due": "monday"}),
    ("email.draft", "write to the vendor", {"to": "the vendor", "topic": None}),
    ("memory.forget", "forget everything", {"query": "everything", "scope": "bulk"}),
    ("calendar.read", "what's on today", {"when": "today"}),
]


def _json_schema(route: str) -> dict:
    names = [s.rstrip("*") for s in SCHEMAS[route]]
    return {
        "type": "object",
        "properties": {n: ({"type": "string", "enum": ["single", "bulk"]} if n == "scope" else {"type": ["string", "null"]}) for n in names},
        "required": names,
        "additionalProperties": False,
    }


def build_messages(route: str, text: str) -> list[dict[str, str]]:
    fields = {s.rstrip("*"): _DESC[s.rstrip("*")] for s in SCHEMAS[route]}
    system = (
        f"{_HEAD} Fields for this action: " + "; ".join(f"{k}: {v}" for k, v in fields.items())
        + ". These guide notes are instructions to you, NEVER values: never output any words from them unless the user said them. "
        "If the user's words do not name the thing (pronouns like it/this/that/them/him/her, 'the last one'), the value is null."
    )
    messages = [{"role": "system", "content": system}]
    for r, t, gold in _FEW:
        messages += [{"role": "user", "content": f"route: {r}\nutterance: {t}"}, {"role": "assistant", "content": json.dumps(gold)}]
    messages.append({"role": "user", "content": f"route: {route}\nutterance: {text}"})
    return messages


async def extract(provider: ProviderConfig, route: str, text: str, *, transport: httpx.AsyncBaseTransport | None = None,
                  timeout: float = 15.0) -> dict | None:
    """Returns the parsed object, or None when the call failed or the output was not a JSON object (never raises)."""
    headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
    body = {
        "model": provider.model, "messages": build_messages(route, text), "max_tokens": 120, "temperature": 0, "stream": False,
        "response_format": {"type": "json_schema", "json_schema": {"name": "args", "schema": _json_schema(route), "strict": True}},
    }
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False) as client:
            response = await client.post(provider.base_url + "/chat/completions", headers=headers, json=body)
            response.raise_for_status()
            parsed = json.loads(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None
