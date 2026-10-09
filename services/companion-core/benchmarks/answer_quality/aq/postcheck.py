"""Post-generation checks for unsupported assertions (Phase 44E evidence-sufficiency work; development only, no reply path uses them).

Each check reads a reply, the question and the evidence items the model was given, and returns flag names. No model is called.
  novel_specific     the reply states a number, a weekday or a month that appears neither in the evidence nor in the question (an invented figure or date)
  world_negative     a sentence denies something about the world ("not available on weekends", "was not shared") with no matching denial in the evidence; denials about the records themselves
                     ("the records do not mention ...") are fine
  recency_claim      (aq.checks) the reply says something is superseded / outdated / newer and no evidence item says so
  subject_property   (aq.checks) a property stated about a named subject never appears with that subject in one item
These are the cheap, deterministic layer. What to do with a flag (regenerate once with the flagged sentence quoted, or fall back to a fixed reply) is decided by the caller."""

from __future__ import annotations

import re

from aq import checks as base
from aq.conflicts import _canonical_numbers
from aq.verify import sentences

_CITE = re.compile(r"\[[^\]]*\]|\(E\d+\)|\bE\d+\b")
_DAY = re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)s?\b", re.IGNORECASE)
_LIST_MARK = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+")
_NEG = re.compile(r"\b(?:not|no|never|isn'?t|aren'?t|wasn'?t|weren'?t|doesn'?t|don'?t|didn'?t|hasn'?t|haven'?t|cannot|can'?t|won'?t|closed|unavailable|none|nobody|nothing)\b", re.IGNORECASE)
# a denial about the records or the assistant's own knowledge is a claim about the evidence, not about the world
_ABOUT_RECORDS = re.compile(
    r"\b(?:no (?:mention|record|information|evidence|reference|details?|data)|not (?:mentioned|specified|stated|recorded|listed|provided|available in|covered|included|shown|given)|"
    r"(?:does|do|did) ?n[o']t (?:say|mention|specify|state|list|include|contain|provide|show|give|cover|have|record|indicate|identify)|nothing (?:in|about|on)|"
    r"i (?:do ?n[o']t|can ?n[o']t|could ?n[o']t|am not able to|am unable to) (?:have|find|see|tell|say|know|determine|confirm|answer|be sure)|unable to (?:find|determine|confirm)|"
    r"no (?:single|clear|direct|explicit)|not (?:clear|certain|sure|explicit(?:ly)?|confirmed)|cannot (?:determine|confirm|say)|isn'?t (?:clear|explicit|stated|mentioned))\b", re.IGNORECASE)
_CONTENT = re.compile(r"[a-z][a-z0-9-]{3,}")
_STOP = frozenset(["that", "this", "with", "from", "have", "been", "were", "will", "would", "could", "should", "there", "their", "about", "which", "these", "those", "than", "then", "they", "them", "what", "when", "where", "while", "also", "into", "only", "some", "such", "more", "most", "other"])


def _clean(reply: str) -> str:
    return _LIST_MARK.sub(" ", _CITE.sub(" ", reply))


def novel_specific(reply: str, question: str, items: dict[str, str]) -> set[str]:
    known_text = " ".join([question, *items.values()])
    known_numbers = _canonical_numbers(known_text)
    known_days = {m.group(0).lower().rstrip("s") for m in _DAY.finditer(known_text)}
    text = _clean(reply)
    novel_numbers = _canonical_numbers(text) - known_numbers
    novel_days = {m.group(0).lower().rstrip("s") for m in _DAY.finditer(text)} - known_days
    return {"novel_specific"} if novel_numbers or novel_days else set()


def world_negative(reply: str, question: str, items: dict[str, str]) -> set[str]:
    evidence = " ".join(items.values()).lower()
    for s in sentences(_clean(reply)):
        if not _NEG.search(s) or _ABOUT_RECORDS.search(s):
            continue
        words = {w for w in _CONTENT.findall(s.lower()) if w not in _STOP}
        # a denial the evidence itself makes: some evidence sentence carries a negation and at least two of this sentence's content words
        supported = False
        for piece in items.values():
            for e in re.split(r"(?<=[.!?])\s+|\n+", piece):
                if _NEG.search(e) and len(words & set(_CONTENT.findall(e.lower()))) >= 2:
                    supported = True
        # the same denial appearing in the question itself ("Is it closed?") is the user's words, not evidence
        if not supported and words and any(w in evidence or w in question.lower() for w in words):
            return {"unsupported_negative"}
    return set()


def about_the_world(reply: str) -> str:
    """The reply without its sentences about the records themselves ("the records do not mention ..."), which assert nothing about the world and are what an honest abstention is made of."""
    return " ".join(s for s in sentences(reply) if not _ABOUT_RECORDS.search(s))


def run_all(reply: str, question: str, items: dict[str, str]) -> dict[str, set[str]]:
    reply = about_the_world(reply)
    return {
        "novel_specific": novel_specific(reply, question, items),
        "world_negative": world_negative(reply, question, items),
        "recency_claim": base.recency_claim(reply, items),
        "subject_property": base.subject_property(question, reply, items),
    }


__all__ = ["novel_specific", "run_all", "world_negative"]
