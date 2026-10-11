"""Explicit references to a named personal record, and the claims a reply may make about one (daily-driver defect, found after Phase 44 closed).

Two failures this closes. A note titled "Tasks for next week" made `What did I write in the notes called 'my Tasks for next week'?` match the task-list
phrase "my tasks", so the owner got "You have no open tasks." And `According to my meeting notes called 'Tasks for next week', what do I need to do?` reached
the model with nothing but the owner's own words, which then wrote "Based on your notes titled ..." over invented content.

The rule: a turn that explicitly names a note or meeting is about that record, whatever words its title contains, so no generic intent handler may claim it
(`parse` returns a reference and the route blanks the generic matchers). The record is then resolved from the stores under the turn's access rules:

* a plain read ("what did I write in the note called X") returns the stored text verbatim, with its title and date, and no model is called;
* any request that needs interpretation fails closed with the existing couldn't-establish wording, even when the record resolves. Answering from a record needs
  the authorised evidence path (Phase 44E), which is not active; this module adds no summariser of its own;
* a record that does not exist, or that this channel may not read, gets the same not-found reply, so a restricted record's existence is not disclosed.

`claims_unsupplied_provenance` is the output-side backstop for the generic model branch: a reply that credits the owner's notes, meetings or similar records is
withheld when the turn supplied no record evidence. It is a fixed pattern check; no model judges its own grounding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from companion_core.action_boundary import is_action_request
from companion_core.meetings.models import READY_FOR_OUTPUTS
from companion_core.meetings.outputs import transcript_lines
from companion_core.semantic import access as rules
from companion_core.semantic.model import AccessContext
from shared.models.response import Privacy

Operation = Literal["retrieve", "question"]

MAX_CHARS = 3000

_NOUN = r"(?:meeting\s+notes?|meetings?|notes?|minutes)"
_QUOTED = r"""(?:"(?P<dq>[^"]+)"|“(?P<cq>[^”]+)”|'(?P<sq>.+?)'(?!\w)|‘(?P<lq>[^’]+)’)"""
_UNQUOTED = r"(?P<uq>[^,?.!;:\"“”‘’]+?)(?=\s*(?:[,?.!;:]|$)|\s+says?\b)"
# "note called X", "meeting notes titled 'X'". The title is a quoted span, or else the words up to the next punctuation.
_TITLED = re.compile(rf"\b{_NOUN}\s+(?:(?:that|which)\s+(?:is|was)\s+)?(?:called|named|titled|entitled)\s+(?:{_QUOTED}|{_UNQUOTED})", re.IGNORECASE)
_DID_WRITE = r"(?:did\s+i\s+(?:write|put|note|jot\s+down|save|record|type)|have\s+i\s+(?:written|put|noted|saved|recorded|typed))(?:\s+down)?"
_ARTICLE = r"(?:the\s+|my\s+|that\s+|our\s+)?"
# "what did I write in 'X'": a quoted title with no noun.
_QUOTE_ONLY = re.compile(rf"^(?:please\s+)?what\s+{_DID_WRITE}\s+(?:in|on)\s+{_ARTICLE}{_QUOTED}\s*[?.!]*$", re.IGNORECASE)
# A source named without a title: which record is meant is not known.
_UNTITLED = re.compile(
    r"\b(?:in|from)\s+(?:my|the|our)\s+(?:meeting\s+)?(?:notes?|meetings?|minutes)\b|"
    r"\b(?:according\s+to|based\s+on|as\s+per)\s+(?:my|the|our)\s+(?:meeting\s+)?(?:notes?|meetings?|minutes)\b",
    re.IGNORECASE,
)
# Asking to list the notes is the existing notes handler's job (titles only, never content).
_LIST_NOTES = re.compile(r"^(?:what(?:'s|\s+is|\s+are)|show|list|tell\s+me)(?:\s+me)?(?:\s+(?:all|everything))?(?:\s+(?:in|of))?\s*(?:my|the)\s+notes\s*[?.!]*$", re.IGNORECASE)
# The skeleton of a request that only asks for the record's own text, with the reference replaced by <ref>.
_RETRIEVE = tuple(re.compile(p, re.IGNORECASE) for p in (
    rf"^(?:please\s+)?what\s+{_DID_WRITE}\s+(?:in|on)\s+{_ARTICLE}<ref>\s*[?.!]*$",
    rf"^(?:please\s+)?(?:show|read|display|open|pull\s+up)(?:\s+me)?(?:\s+out)?\s+(?:(?:the\s+)?(?:contents?|text|body)\s+of\s+)?{_ARTICLE}<ref>\s*[?.!]*$",
    rf"^(?:please\s+)?what(?:'s|\s+is|\s+was)\s+(?:in|on)\s+{_ARTICLE}<ref>\s*[?.!]*$",
    rf"^(?:please\s+)?what\s+does\s+{_ARTICLE}<ref>\s+say\s*[?.!]*$",
))
# Only a question or a request to read can be about a record. An imperative that changes something never starts with these, and
# `is_action_request` is checked as well, so "delete the note called X" stays with the action boundary.
_OPENER = re.compile(
    r"^(?:(?:please|kindly|ok(?:ay)?|hey|so|and|also)[\s,]+|reachy[\s,:]+)*"
    r"(?:what|which|who|when|where|how|why|according|based|in|from|show|read|tell|give|summari[sz]e|list|open|pull|do|does|did|is|are|have|has)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RecordReference:
    title: str | None  # None: a source was named ("in my notes") but not which record
    operation: Operation


def _clean(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def without_titles(text: str) -> str:
    """`text` with any quoted span and any "called X" title removed, so words inside a note's title are never read as part of the request."""
    return re.sub(r"\s+", " ", _TITLED.sub(" ", re.sub(_QUOTED, " ", text))).strip()


def parse(text: str) -> RecordReference | None:
    """The explicit record reference in `text`, or None. Fixed patterns; no model."""
    stripped = text.strip()
    if not stripped or stripped.startswith("/") or not _OPENER.match(stripped) or is_action_request(stripped):
        return None
    quoted = _QUOTE_ONLY.match(stripped)
    if quoted:
        return RecordReference(_clean(next(v for v in quoted.groupdict().values() if v)), "retrieve")
    titled = _TITLED.search(stripped)
    if titled:
        title = _clean(next(v for v in titled.groupdict().values() if v))
        skeleton = re.sub(r"\s+", " ", stripped[: titled.start()] + "<ref>" + stripped[titled.end():]).strip()
        retrieve = any(p.match(skeleton) for p in _RETRIEVE)
        return RecordReference(title, "retrieve" if retrieve else "question")
    if _UNTITLED.search(stripped) and not _LIST_NOTES.match(stripped):
        return RecordReference(None, "question")
    return None


# -- resolution ---------------------------------------------------------------------------------------------------------------------

def _norm(title: str) -> str:
    return re.sub(r"\s+", " ", title.casefold()).strip(" .,:;!?\"'")


def _candidates(title: str) -> list[str]:
    """The owner's wording, and the same without a leading possessive ("my Tasks for next week" for a note titled "Tasks for next week")."""
    wanted = _norm(title)
    stripped = re.sub(r"^(?:my|the|our|your)\s+", "", wanted)
    return [wanted] if stripped == wanted else [wanted, stripped]


@dataclass(frozen=True)
class Resolved:
    kind: Literal["note", "meeting"]
    title: str
    text: str
    sensitivity: Privacy
    stamp: str  # a date, for the owner to tell which version they were shown


def _readable(access: AccessContext, sensitivity: Privacy, project_scope: str | None, local_only: bool) -> bool:
    return (rules.within_ceiling(sensitivity, access.sensitivity_ceiling) and rules.scope_permits(access, project_scope)
            and rules.destination_permits(access, local_only))


async def resolve(title: str, *, planner, meetings, access: AccessContext) -> list[Resolved]:
    """Every readable note or meeting whose title is the one named, exactly (case, spacing and edge punctuation aside). A record this access may not read is
    absent from the result, so nothing downstream can distinguish it from one that does not exist. The first wording that matches anything wins."""
    notes = [n for n in await planner.list_notes() if _readable(access, n.sensitivity, n.project_scope, False)]
    ready = [m for m in await meetings.list_meetings()
             if m.status in READY_FOR_OUTPUTS and m.transcript_segments and _readable(access, m.sensitivity, m.project_scope, True)]
    for wanted in _candidates(title):
        found = [Resolved("note", n.title, n.body.strip(), n.sensitivity, f"{n.updated_at:%d %b %Y}") for n in notes if _norm(n.title) == wanted]
        found += [Resolved("meeting", m.title, "\n".join(transcript_lines(m)), m.sensitivity, f"{(m.started_at or m.created_at):%d %b %Y}")
                  for m in ready if _norm(m.title) == wanted]
        if found:
            return found
    return []


async def find(query: str, kind: Literal["note", "meeting", "any"], *, planner, meetings, access: AccessContext) -> list[Resolved]:
    """Every readable note or meeting whose title or text contains `query` (case aside), under the same access rules as `resolve`. A plain substring test, no model; a record this
    access may not read is absent from the result."""
    wanted = query.casefold().strip()
    if not wanted:
        return []
    found: list[Resolved] = []
    if kind in ("note", "any"):
        for n in await planner.list_notes(query):
            if _readable(access, n.sensitivity, n.project_scope, False):
                found.append(Resolved("note", n.title, n.body.strip(), n.sensitivity, f"{n.updated_at:%d %b %Y}"))
    if kind in ("meeting", "any"):
        for m in await meetings.list_meetings():
            if m.status in READY_FOR_OUTPUTS and m.transcript_segments and _readable(access, m.sensitivity, m.project_scope, True):
                text = "\n".join(transcript_lines(m))
                if wanted in m.title.casefold() or wanted in text.casefold():
                    found.append(Resolved("meeting", m.title, text, m.sensitivity, f"{(m.started_at or m.created_at):%d %b %Y}"))
    return found


# -- replies (fixed text; the stored text is quoted, never paraphrased) -------------------------------------------------------------

COULD_NOT_ESTABLISH = "I couldn't establish that from the records I was able to check."  # the existing 44E wording (selective_answer.ZERO_EVIDENCE_REPLY)


def not_found_reply(title: str) -> str:
    return f'I couldn\'t find a note or meeting called "{title}".'


def ambiguous_reply(title: str) -> str:
    return f'More than one record is called "{title}", so I haven\'t picked one.'


def record_reply(record: Resolved) -> str:
    label = "note" if record.kind == "note" else "meeting"
    head = f'Your {label} "{record.title}" ({record.stamp})'
    if not record.text:
        return f"{head} is empty."
    body = record.text if len(record.text) <= MAX_CHARS else record.text[:MAX_CHARS].rstrip() + f"\n\n(Showing the first {MAX_CHARS} of {len(record.text)} characters.)"
    suffix = " transcript" if record.kind == "meeting" else ""
    return f"{head}{suffix}:\n\n{body}"


# -- the provenance backstop ----------------------------------------------------------------------------------------------------------

_RECORDS = r"(?:(?:meeting|saved|personal)\s+)?(?:notes?|meetings?|minutes|records?|memor(?:y|ies)|documents?|files?|calendar|tasks?|to-?dos?|reminders?|emails?|inbox)"
_PROVENANCE = re.compile(
    rf"\b(?:according\s+to|based\s+on|as\s+per|per|from|as\s+(?:stated|noted|written|recorded|described|mentioned|listed)\s+in)\s+(?:your|the\s+owner's)\s+{_RECORDS}\b|"
    rf"\byour\s+{_RECORDS}\s+(?:say|says|show|shows|state|states|mention|mentions|indicate|indicates|list|lists|include|includes|note|notes\s+that)\b|"
    r"\byou\s+(?:wrote|noted|recorded|jotted|saved)\b|"
    rf"\b(?:notes?|meetings?|minutes)\s+(?:titled|called|named)\b",
    re.IGNORECASE,
)
_NEGATED = re.compile(r"\b(?:can(?:'|’)?t|cannot|can\s+not|couldn(?:'|’)?t|don(?:'|’)?t|do\s+not|doesn(?:'|’)?t|no\s+access|not\s+able|unable|without|haven(?:'|’)?t|have\s+not|no\s+record)\b", re.IGNORECASE)


def claims_unsupplied_provenance(reply: str) -> bool:
    """True when a sentence of `reply` credits the owner's own records, unless that sentence is a plain denial ("I can't see your notes"). The caller
    withholds the reply when the turn supplied no record evidence."""
    return any(_PROVENANCE.search(s) and not _NEGATED.search(s) for s in re.split(r"(?<=[.!?])\s+|\n+", reply))
