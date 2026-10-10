"""Explicit value transitions (Phase 44, final development pass, 2026-10-10).

A record sentence can state a value together with where that value stands: configured now, deployed, decided on, planned, retired, rolled back. The old reader treated a sentence with two values of the relation's
kind as unreadable ("multiple_values") and a sentence containing "retired" as entirely past, so a plain statement such as

    "As of October, the Cedar default model is Swift-20B; the Merlin-2B model has been retired."

was withheld as unclear for every question about the Cedar default model, and "So the decision is to keep Swift-20B as the default model." was read as the current default model.

This module reads ONE sentence and says what status each value in it has, from the sentence's own words and nothing else. Statuses:

    configured   a plain present or undated statement of the value ("is", "currently", "as of October ... is"). Counts as the current value.
    deployed     the sentence says the change HAPPENED ("switched to", "moved to", "rolled out", "deployed", "went live", "from X to Y"). Counts as the current value.
    decided      the sentence reports a decision ("the decision is to", "agreed", "decided"). Not a statement that anything is in place: never the current value, reported as a decision only.
    planned      the sentence is about the future ("will switch", "plans to", "scheduled to"). Same: never the current value.
    retired      the value is stated to be out of use ("<value> ... has been retired / removed / deprecated"), in the tail of a transition sentence or as the old side of "from X to Y" / "X replaces Y".
    rolled_back  the value was rolled back (the old side of "rolled back from X to Y"; the new side, "rolled back to X", is deployed).

What is NOT inferred, on purpose: that a decision was carried out; that a retired value was the previous setting (the sentence does not say so); that a record is newer than another (no timestamp is read here);
that a retirement in one record overrides a statement in another (a conflict stays a conflict, see states.py). A retired or rolled-back value never becomes an answer; it can only make a competing record's claim
unsafe to state. Pure and deterministic: no model, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass

CONFIGURED, DEPLOYED, DECIDED, PLANNED, RETIRED, ROLLED_BACK = "configured", "deployed", "decided", "planned", "retired", "rolled_back"
LIVE = frozenset({CONFIGURED, DEPLOYED})  # statuses that can be the current value
PENDING = frozenset({DECIDED, PLANNED})  # reported as a decision or a plan, never as the value in effect
OUT_OF_USE = frozenset({RETIRED, ROLLED_BACK})

_DECIDED = re.compile(r"\b(?:decid\w*|decision|agreed?|agreement|resolved|voted|settled on|chose|chosen)\b", re.IGNORECASE)
_PLANNED = re.compile(r"\b(?:going to|plans? to|planned|planning to|scheduled (?:to|for)|intends? to|due to (?:switch|move|change|migrate|deploy|roll))\b|"
                      r"\bwill\s+(?:soon\s+|then\s+)?(?:be\s+)?(?:the\s+)?(?:switch\w*|mov\w*|chang\w*|migrat\w*|deploy\w*|roll\w*|upgrad\w*|replac\w*|adopt\w*|us\w+|keep|kept|become|default)\b", re.IGNORECASE)
_COMPLETED = re.compile(r"\b(?:switched|moved|changed|migrated|upgraded|downgraded|deployed|rolled out|rolled back|went live|promoted|cut over)\b", re.IGNORECASE)
_RETIRE = r"(?:retired|decommissioned|deprecated|removed|phased out|discontinued|sunset|dropped)"
_NUMWORD = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"

# Value forms for the kinds on which a transition is read. Group 1 is the value. Only kinds whose value is a name or a count can carry a transition; the others are read as before.
_VALUE = {
    "model": r"[A-Z][a-z]+-\d+B",
    "host": r"(?:gpu|cpu|edge|batch) host",
    "number": rf"{_NUMWORD}",
    "day": r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
    "month": r"(?:january|february|march|april|may|june|july|august|september|october|november|december)",
    "hours": r"\d{1,2} to \d{1,2}",
    "time": r"\d{1,2}(?::\d{2})?",
    "person": r"[A-Z][a-z]+ [A-Z][a-z]+",
}


@dataclass(frozen=True)
class Statement:
    head: str  # the part of the sentence that is read for the value, scope and subject (a retirement tail or a "from <old>" is cut off)
    status: str  # status of the value(s) found in `head`
    others: tuple[tuple[str, str], ...] = ()  # (value text as written, status): values the sentence names only to say where THEY stand (retired, rolled back)


def read(sentence: str, kind: str) -> Statement:
    """Statuses for one record sentence. A sentence with no transition wording is returned unchanged with status `configured`."""
    value = _VALUE.get(kind)
    flags = 0 if kind in ("model", "person") else re.IGNORECASE
    status = DECIDED if _DECIDED.search(sentence) else PLANNED if _PLANNED.search(sentence) else CONFIGURED
    if value is None:
        return Statement(sentence, status)

    # tail: "<head>; the <old> [model] has been retired."  The tail names no subject and only the old value.
    if ";" in sentence:
        head, _, tail = sentence.rpartition(";")
        m = re.fullmatch(rf"\s*(?:and\s+)?(?:the\s+)?(?P<old>{value})(?:\s+(?:model|host|machine|setting|value|limit|window|configuration|one))?\s+(?:has been|have been|was|were|is|are|got)\s+(?:now\s+|since\s+|formally\s+)?{_RETIRE}\s*[.!]?\s*", tail, flags)
        if m and head.strip():
            return Statement(head.strip(), status, ((m.group("old"), RETIRED),))

    # "switched/moved/changed/migrated/rolled back ... from <old> to <new>": the new value is what the change produced, the old one is out of use.
    m = re.search(rf"\b(?P<verb>switch\w*|mov\w*|chang\w*|migrat\w*|upgrad\w*|downgrad\w*|roll\w*(?: back)?)\b[^.;]*?\bfrom\s+(?P<old>{value})\s+(?P<to>to)\s+(?P<new>{value})", sentence, flags)
    if m:
        cut = sentence[: m.start("old") - len("from ")].rstrip() + " " + sentence[m.end("old"):].lstrip()
        old_status = ROLLED_BACK if "back" in m.group("verb").lower() else RETIRED
        return Statement(cut, status if status != CONFIGURED else DEPLOYED, ((m.group("old"), old_status),))

    # "<new> replaces <old>" / "replaced <old> with <new>"
    m = re.search(rf"\b(?P<new>{value})\b[^.;]*?\breplace[sd]?\s+(?:the\s+)?(?P<old>{value})\b", sentence, flags)
    if m and m.group("new").casefold() != m.group("old").casefold():
        cut = sentence[: m.start("old")] + sentence[m.end("old"):]
        return Statement(cut, status if status != CONFIGURED else DEPLOYED, ((m.group("old"), RETIRED),))
    m = re.search(rf"\breplaced\s+(?:the\s+)?(?P<old>{value})\s+with\s+(?P<new>{value})\b", sentence, flags)
    if m and m.group("new").casefold() != m.group("old").casefold():
        cut = sentence[: m.start("old")] + sentence[m.end("old"):].replace("with ", "", 1)
        return Statement(cut, status if status != CONFIGURED else DEPLOYED, ((m.group("old"), RETIRED),))

    if status == CONFIGURED and _COMPLETED.search(sentence):
        status = DEPLOYED
    return Statement(sentence, status)
