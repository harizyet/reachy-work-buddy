"""Post-answer claim verification: deterministic checks of a reply against the evidence it was given, and an optional second model pass, for the
experiment in `verify_experiment.py` (Phase 44E follow-up). Nothing here runs in production; it exists to measure whether a check is worth building.

A verifier sees only the question, the reply and the evidence items (text, ids). It returns a set of flag names; it never edits the reply."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from companion_core.knowledge.context import (
    _NUMWORDS,
    _quantities,
    find_number_conflicts,
)

from aq import scoring as v1
from aq.scoring_v2 import entry_texts

_STOP = {"this", "that", "with", "from", "have", "been", "were", "will", "not", "but", "you", "your", "into", "than", "then", "they", "them", "their", "there", "which", "when", "what", "where", "who", "whom", "whose", "after", "before", "while", "about", "over", "under", "also", "each", "other", "such", "only", "same", "more", "most", "some", "any", "can", "could", "would", "should", "may", "might", "records", "record", "owner", "owners", "evidence", "provided", "based", "according", "item", "items", "mentioned", "states", "stated", "says", "said", "mention", "information", "available", "specific"}
_WORD = re.compile(r"[a-z][a-z0-9-]{3,}")
_CITE = re.compile(r"\s*\[[^\]]*E\d+[^\]]*\]")
_NUM = re.compile(r"\b\d+(?:[.:]\d+)?\b")
_CAP = re.compile(r"(?<![.!?:]\s)(?<!^)\b[A-Z][a-z]{2,}\b")


def content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def sentences(reply: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", _CITE.sub("", reply))
    return [re.sub(r"^[\s\-*\d.)]+", "", p).strip() for p in parts if p.strip()]


def factual(sentence: str) -> bool:
    """A sentence that asserts something about the world: enough content words, and not itself an abstention or a pointer to the evidence."""
    return len(content_words(sentence)) >= 3 and not v1.abstained(sentence)


def evidence_words(texts: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for t in texts.values():
        out |= content_words(t)
    return out


def lexical_support(question: str, reply: str, texts: dict[str, str], tau: float = 0.6) -> set[str]:
    """V1: every factual sentence must draw at least `tau` of its content words from the evidence or the question."""
    pool = evidence_words(texts) | content_words(question)
    for s in sentences(reply):
        if factual(s):
            words = content_words(s)
            if words and len(words & pool) / len(words) < tau:
                return {"unsupported_sentence"}
    return set()


def anchor_support(question: str, reply: str, texts: dict[str, str]) -> set[str]:
    """V2: numbers and capitalised names in the reply must appear in the evidence or the question."""
    pool = " ".join(texts.values()).lower() + " " + question.lower()
    clean = _CITE.sub("", reply)
    flags = set()
    for n in _NUM.findall(clean):
        if n not in pool and not re.search(rf"\b{re.escape(n)}\b", pool):
            flags.add("unsupported_number")
    spoken = {w.lower(): i for w, i in _NUMWORDS.items()}
    for w in re.findall(r"\b[a-z]+\b", clean.lower()):
        if w in spoken and str(spoken[w]) not in pool and w not in pool:
            flags.add("unsupported_number")
    for name in _CAP.findall(clean):
        if name.lower() not in pool and name.lower() not in {"the", "based", "according", "evidence"}:
            flags.add("unsupported_name")
    return flags


def cited_support(question: str, reply: str, texts: dict[str, str], tau: float = 0.5) -> set[str]:
    """V3: a sentence that cites an item must draw `tau` of its content words from that item; with ids on offer, a factual sentence with no citation is flagged."""
    flags = set()
    raw = re.split(r"(?<=[.!?])\s+|\n+", reply)
    for chunk in raw:
        ids = re.findall(r"E\d+", " ".join(re.findall(r"\[[^\]]*\]", chunk)))
        s = sentences(chunk)
        if not s or not factual(s[0] if len(s) == 1 else " ".join(s)):
            continue
        text = " ".join(s)
        if not ids:
            flags.add("uncited_claim")
            continue
        pool = set()
        for eid in ids:
            pool |= content_words(texts.get(eid, ""))
        words = content_words(text)
        if words and len(words & pool) / len(words) < tau:
            flags.add("claim_not_in_cited_item")
    return flags


def relevance_gate(question: str, reply: str, texts: dict[str, str], tau: float = 0.4) -> set[str]:
    """V5: if no single evidence item shares `tau` of the question's content words, the evidence does not address the question, so an answer that does not
    abstain is flagged."""
    q = content_words(question)
    if not q or v1.abstained(reply):
        return set()
    best = max((len(q & content_words(t)) / len(q) for t in texts.values()), default=0.0)
    return {"answers_without_relevant_evidence"} if best < tau else set()


def conflict_check(question: str, reply: str, texts: dict[str, str]) -> set[str]:
    """V4: if two items give different quantities of the same kind for the same subject, the reply must mention a value from each side."""
    if len(texts) < 2:
        return set()
    conflicts = find_number_conflicts(texts)
    low = _CITE.sub("", reply).lower()
    for a, others in conflicts.items():
        for b in others:
            if a >= b:
                continue
            va = {q for q in _quantities(texts[a])}
            vb = {q for q in _quantities(texts[b])}
            only_a, only_b = va - vb, vb - va
            if not only_a or not only_b:
                continue

            def mentioned(values) -> bool:
                for kind, lo, hi in values:
                    nums = [lo] + ([hi] if hi else [])
                    if all((f"{int(n)}" in low or any(w for w, v in _NUMWORDS.items() if v == n and w in low)) for n in nums):
                        return True
                return False

            if not (mentioned(only_a) and mentioned(only_b)):
                return {"conflict_not_reported"}
    return set()


DETERMINISTIC: dict[str, Callable[..., set[str]]] = {
    "V1_lexical": lexical_support, "V2_anchors": anchor_support, "V3_cited": cited_support, "V5_relevance": relevance_gate, "V4_conflict": conflict_check,
}


def check(name: str, row: dict[str, Any], question: str) -> set[str]:
    texts = entry_texts(row["context"].get("text", ""))
    if not texts:
        return set()
    return DETERMINISTIC[name](question, row["reply"], texts)
