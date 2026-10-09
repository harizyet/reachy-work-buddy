"""Section-level evidence coverage (Phase 44E experiment, development only; nothing here is wired into a reply path).

The existing assessor (`sufficiency.py`, frozen as the comparator) asks whether some evidence ITEM holds a named thing and an aspect word of the question. An item can be a whole record, so a
fact about one thing and a fact about another, written near each other, satisfy it together. This variant asks the same question of PASSAGES: a Markdown section's sentences, a note's sentences,
a meeting line. A passage inherits its item's title, section heading and project scope as context (a "Lantern runbook" sentence is about Lantern), so a name in a title still counts, but a name in
one sentence no longer vouches for an aspect in a different sentence.

Optionally (`descriptors=True`) the word that directly follows a named thing in the question ("Quill QUEUE", "Beacon SUPPORT line") is treated as part of the name rather than as an aspect, since
"queue" in a sentence about Quill says nothing about the thing being asked of it.

Verdicts, notes and retry queries are the existing ones (same `Assessment`), so the only difference between the two mechanisms is the unit of co-occurrence. Deterministic and lexical: it can be wrong
in both directions, and it is an experimental signal, not a gate."""

from __future__ import annotations

import re
from collections.abc import Sequence

from companion_core.knowledge.sufficiency import (
    _NUMBER,
    _STOP,
    _WORD,
    Assessment,
    Piece,
    _family,
    _mentions,
    question_terms,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def passages(piece: Piece) -> list[Piece]:
    """Sentences of the piece, each carrying the piece's title, the nearest Markdown heading and the scope as context."""
    heading = ""
    out: list[Piece] = []
    for line in piece.text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
            continue
        for sentence in _SENTENCE.split(line):
            if sentence.strip():
                out.append(Piece(text=sentence.strip(), title=f"{piece.title} {heading}".strip(), scope=piece.scope))
    return out or [piece]


def _descriptors(question: str, names: list[str]) -> set[str]:
    """Lower-case words that sit directly after a named thing in the question."""
    words = [m.group(0) for m in _WORD.finditer(question)]
    out: set[str] = set()
    for i, w in enumerate(words[:-1]):
        if w.removesuffix("'s").removesuffix("’s") in names:
            nxt = words[i + 1]
            if nxt.lower() not in _STOP and not nxt[:1].isupper():
                out.add(nxt.lower())
    return out


def assess_sections(question: str, pieces: Sequence[Piece], *, descriptors: bool = False) -> Assessment:
    names, aspects = question_terms(question)
    if not pieces:
        return Assessment("none", tuple(names), tuple(aspects))
    named = [n for n in names if not _NUMBER.fullmatch(n)]
    absent = tuple(n for n in named if not _mentions(n, pieces))
    if absent:  # a name that appears in no item at all: the same item-level test as the comparator
        families = {_family(n) for n in absent if _family(n)}
        words = {w for p in pieces for w in re.findall(r"[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", p.haystack)}
        similar = tuple(sorted({w for w in words if "-" in w and _family(w) in families and w.lower() not in {a.lower() for a in absent}}))
        return Assessment("entity_absent", tuple(names), tuple(aspects), absent_entities=absent, all_absent=len(absent) == len(named), similar=similar)
    ps = [p for piece in pieces for p in passages(piece)]
    skip = _descriptors(question, names) if descriptors else set()
    judged = [a for a in aspects if a not in skip]
    uncovered = tuple(a for a in judged if not _mentions(a, ps))
    covered = [a for a in judged if a not in uncovered]
    if named and covered:
        with_name = {id(p) for n in named for p in _mentions(n, ps)}
        with_aspect = {id(p) for a in covered for p in _mentions(a, ps)}
        if not (with_name & with_aspect):
            holders = tuple(dict.fromkeys(p.title or p.scope or p.text[:40] for a in covered for p in _mentions(a, ps)))
            return Assessment("entity_mismatch", tuple(names), tuple(aspects), uncovered_aspects=uncovered, aspect_titles=holders)
    if judged and not covered:
        return Assessment("topic_missing", tuple(names), tuple(aspects), uncovered_aspects=uncovered)
    specific = tuple(a for a in uncovered if any(ch.isdigit() for ch in a))
    if specific:
        return Assessment("partial", tuple(names), tuple(aspects), uncovered_aspects=specific)
    return Assessment("sufficient", tuple(names), tuple(aspects))


__all__ = ["assess_sections", "passages"]
