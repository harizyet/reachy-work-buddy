"""A message that asks to READ something and also to CHANGE or SEND something.

The deterministic chain claims the read half ("What are my tasks?") and the 44H boundary only recognises a write that starts a clause with a known object, so "What are my tasks?
Also mark them all done." used to be answered as the list alone, as if the whole request had been handled. This module recognises the shape and returns one fixed reply that names the
operation that was not performed. It performs neither half: no multi-step execution, and no write is authorised. A message that starts with a write, or that is a supported
write (adding a task, setting an alarm), is not this module's business; `action_boundary` and the existing handlers keep those."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Verbs that change or send something and that the assistant cannot do from a chat. "add", "set", "create", "remind" and "forget" are deliberately absent: those have their own handlers.
_VERBS = (
    "mark|delete|remove|clear|erase|wipe|cancel|complete|finish|tick|send|email|e-mail|forward|archive|reschedule|rename|snooze|dismiss|update|edit|text|message|"
    "share|post|publish|submit|approve|confirm|move"
)
_READ_FIRST = re.compile(
    r"^\W*(?:(?:please|kindly|ok(?:ay)?|hey|so|reachy)[\s,:]+)*(?:what|which|who|when|where|how many|show|list|tell|give|read|find|check|do i|have i|are there|is there|any)\b",
    re.IGNORECASE,
)
_WRITE_CLAUSE = re.compile(
    rf"^\W*(?:(?:and|then|also|please|now|just|afterwards?|after that|next)[\s,]+)*(?:(?:can|could|would|will) you\s+)?(?:please\s+)?(?P<verb>{_VERBS})\b\s+\S",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"[.!?;:]+\s+|\s*,\s*|\s+(?:and then|and also|then|also|and|but)\s+", re.IGNORECASE)

MIXED_REPLY = ("That asks me to read something and also to {verb} something. I can't {verb} anything from here, so I haven't made any changes, and I haven't run the read part either. "
               "Ask for the read on its own if you want it.")


@dataclass(frozen=True)
class Mixed:
    verb: str


def detect(text: str) -> Mixed | None:
    """The write verb of a message that starts as a read and also asks for a write, or None."""
    clauses = [c for c in _SPLIT.split(text.strip()) if c and c.strip()]
    if len(clauses) < 2 or not _READ_FIRST.match(clauses[0]):
        return None
    for clause in clauses[1:]:
        found = _WRITE_CLAUSE.match(clause)
        if found:
            return Mixed(found.group("verb").lower())
    return None


def reply(mixed: Mixed) -> str:
    return MIXED_REPLY.format(verb=mixed.verb)
