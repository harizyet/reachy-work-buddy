"""Deterministic grounding validator for model-extracted tool arguments. The model proposes; this code decides.

validate(route, schema, args, text) -> Validation(status, args, reasons)
A value is eligible only if every content word in it appears in the user's utterance. No model is consulted.
Written against the bench/router benchmarks (docs/shadow-router.md): it is deliberately strict, so an over-withheld
request becomes a clarification question rather than a wrong action."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SCHEMAS: dict[str, tuple[str, ...]] = {  # trailing * = required
    "email.draft": ("to*", "topic*"),
    "tasks.capture": ("title*", "due"),
    "tasks.complete": ("task*",),
    "memory.capture": ("content*",),
    "memory.forget": ("query*", "scope"),
    "memory.read": ("query*",),
    "calendar.read": ("when",),
    "email.read": ("sender",),
    "tasks.read": ("query",),
    "rag.query": ("query*",),
    "web.search": ("query*",),
    "clock.read": ("place",),
}
WRITE_ROUTES = {"email.draft", "tasks.capture", "tasks.complete", "memory.capture", "memory.forget"}

_STOP = {"the", "a", "an", "my", "our", "your", "to", "of", "for", "on", "at", "in", "about", "that", "and", "is", "was", "i", "me",
         "i'm", "it's", "some", "with", "from", "by"}
_REF_ONLY = {"it", "this", "that", "them", "those", "these", "one", "ones", "he", "him", "she", "her", "they", "thing", "things", "stuff",
             "something", "anything", "last", "previous", "same", "task", "tasks", "note", "notes", "item", "other", "latter", "former",
             "what", "just", "said", "there", "here", "later"}
_PLACEHOLDER = {"null", "none", "n/a", "na", "nil", "undefined", "unknown", "unspecified", "string", "value", "tbd", ""}
_SCHEMA_WORDS = {"copied", "trimmed", "utterance", "stated", "exactly", "recipient", "named", "filler"}
# Words naming the command or the tool's own domain, not a target: a value made only of these (plus references) copies the instruction.
_CMD = {
    "add", "mark", "done", "complete", "completed", "finish", "finished", "close", "cross", "off", "tick", "check", "delete", "remove", "forget", "erase", "wipe", "remember", "recall", "note", "save", "store", "keep", "mind", "down", "look", "up", "search", "find", "online", "file", "document", "doc", "list", "to-do", "todo", "memory", "say", "said", "tell", "told", "earlier", "before", "you", "do", "does", "did", "what", "put", "as", "send", "write", "draft", "email", "reply", "back", "on", "how", "why", "when", "who", "where", "is", "are", "will", "go", "going"
}
_MULTI_RE = re.compile(r"\b(or|and|both|either|neither|each|first one|second one)\b|,", re.IGNORECASE)
_BULK_RE = re.compile(
    r"\b(everything|all (of )?(my|the|your|our)|all notes|all memor|entire|whole|every (single )?(thing|note|memor|fact)|wipe|"
    r"clear (out )?(my|the|your|all)|erase (all|my|the|everything))\b", re.IGNORECASE)
_BARE_REF = {"it", "this", "that", "them", "those", "these", "him", "her", "one", "ones"}
_DEICTIC = re.compile(
    r"^(what|whatever|the thing|the stuff|anything) (i|we) (just |recently |earlier )?(said|told you|mentioned|asked)( you)?"
    r"( (a|just|earlier|before|recently|moment|minute|second|while)\b.*)?$", re.IGNORECASE)


@dataclass
class Validation:
    status: str  # ok | needs_clarification | bulk_refused
    args: dict[str, str | None]
    reasons: list[str] = field(default_factory=list)


def _toks(s: object) -> list[str]:
    return re.findall(r"[a-z0-9@.']+", str(s).lower().replace("’", "'"))


def _stem(t: str) -> str:
    t = t.strip(".'")
    t = t.removesuffix("'s")
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


def _content(s: str) -> list[str]:
    return [_stem(t) for t in _toks(s) if t not in _STOP and _stem(t)]


_REF_STEMS = {_stem(x) for x in _REF_ONLY}
_CMD_STEMS = {_stem(x) for x in _CMD}


def _check_value(value: object, text: str) -> tuple[str | None, str | None]:
    if value is None:
        return None, "missing"
    if not isinstance(value, str):
        return None, "not_a_string"
    v = value.strip()
    if v.lower() in _PLACEHOLDER:
        return None, "placeholder"
    ct = _content(v)
    if not ct:
        return None, "empty"
    vt, ut = set(_toks(v)), set(_toks(text))
    if vt & _SCHEMA_WORDS and not (vt & _SCHEMA_WORDS) <= ut:
        return None, "schema_text_copied"
    if all(t in _REF_STEMS for t in ct):
        return None, "unresolved_reference"
    if all(t in _REF_STEMS or t in _CMD_STEMS for t in ct):
        return None, "unresolved_reference"
    have = {_stem(t) for t in _toks(text)}
    missing = [t for t in ct if t not in have]
    if missing:
        return None, "ungrounded:" + ",".join(missing)
    return v, None


def _structural(value: str, text: str) -> str | None:
    """The value must not be the instruction itself (no verb list)."""
    ut, vt = _toks(text), _toks(value)
    if not vt:
        return None
    n = len(vt)
    pos = next((i for i in range(len(ut) - n + 1) if ut[i:i + n] == vt), None)
    if pos is None:
        pos = 0 if {_stem(t) for t in vt} >= {_stem(t) for t in ut[:1]} else 1
    if pos == 0 and len(ut) > 3 and n >= 2:
        return "copies_instruction_start"
    if set(vt) & _BARE_REF:
        return "contains_reference_word"
    if _DEICTIC.match(value.strip()):
        return "deictic_description"
    return None


def validate(route: str, args: dict | None, text: str) -> Validation:
    schema = SCHEMAS[route]
    reasons: list[str] = []
    out: dict[str, str | None] = {}
    ok = True
    for spec in schema:
        required = spec.endswith("*")
        name = spec.rstrip("*")
        raw = (args or {}).get(name)
        if name == "scope":
            # Bulk scope comes from the words, never from the model alone; either signal escalates.
            out[name] = "bulk" if (raw == "bulk" or _BULK_RE.search(text)) else "single"
            continue
        val, why = _check_value(raw, text)
        if val and route in ("tasks.complete", "memory.forget") and name in ("task", "query") and _MULTI_RE.search(val):
            val, why = None, "multiple_targets"
        if val and (route in WRITE_ROUTES or route in ("rag.query", "memory.read")) and name not in ("due", "when", "place", "sender"):
            why_struct = _structural(val, text)
            if why_struct:
                val, why = None, why_struct
        out[name] = val
        if why and (required or why not in ("missing", "placeholder", "empty")):
            if required:
                ok = False
                reasons.append(f"{name}:{why}")
            else:
                reasons.append(f"{name}:dropped_{why}")  # an optional field is never executed unless grounded
    if route == "memory.forget" and out.get("scope") == "bulk":
        return Validation("bulk_refused", out, [*reasons, "bulk_scope"])
    return Validation("ok" if ok else "needs_clarification", out, reasons)
