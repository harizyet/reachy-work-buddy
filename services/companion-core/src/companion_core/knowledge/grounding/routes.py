"""C3: authoritative structured-store routing where a relation maps cleanly. For now exactly one mapping that the survey found to be clean and that text retrieval handles badly: WHO ATTENDED a
meeting = the meeting record's speaker names. The caller passes only meetings already authorised for this turn; the route reads nothing else. It returns deterministic text with the meeting as source, or a
deterministic "no such meeting" (which reveals nothing the caller could not already see, because only authorised meetings are passed in)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from companion_core.knowledge.grounding.propositions import read_question


@dataclass(frozen=True)
class Routed:
    text: str
    sources: tuple[str, ...]  # logical meeting ids
    found: bool


def route_attendees(question: str, meetings: Sequence[dict]) -> Routed | None:
    """`meetings`: dicts with id, title, speaker_names ({speaker: name}). None when the question is not an attendee question (fall through to the normal path)."""
    props = read_question(question)
    if not any(p.structured and p.relation == "attends" for p in props):
        return None
    subjects = [s for p in props for s in p.subjects]
    for m in meetings:
        title = m["title"].lower()
        if subjects and any(re.search(rf"(?<![a-z0-9]){re.escape(s.lower())}", title) for s in subjects):
            names = list(dict.fromkeys(m["speaker_names"].values()))
            who = ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1] if names else "nobody is recorded"
            return Routed(f"The {m['title']} meeting had these speakers: {who}.", (f"meeting:{m['id']}",), True)
    named = ", ".join(subjects) or "that"
    return Routed(f"I don't have a record of a meeting for {named}.", (), False)
