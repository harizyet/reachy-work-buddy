"""Evidence sufficiency (Phase 44E, development only; nothing here is wired into a reply path).

Before a model sees retrieved evidence, ask a deterministic question: does the evidence actually speak to what was asked? The check reads the question's named things
(people, projects, models, numbers) and its other content words ("aspects"), and the evidence the builder will show, and returns one verdict:

  none              no evidence at all
  entity_absent     something the question names appears in no evidence item (or the evidence names only a different thing of the same family, "Falcon-3B" vs "Falcon-7B")
  entity_mismatch   the evidence holds the aspect asked about ("rollback window") but never together with the thing asked about ("Harbor"): the answer would be about another entity
  topic_missing     the evidence names the thing asked about but holds none of the question's other words (a possible paraphrase, so a note and never a gate)
  partial           every named thing appears, but an identifier-like word of the question (it contains a digit, "p95") appears in no evidence item
  sufficient        otherwise

Paraphrase is not partial: "date", "long" or "keep" in a question rarely appear verbatim in the evidence that answers it (measured: lexical gaps on 56 of 83 answerable development
questions), so ordinary words never produce a verdict. Numbers the question offers as candidates ("Is it 45 minutes?") are not named things either.

No model is called and nothing is learned from data: the rules are lexical, so the check can be wrong in both directions (a paraphrase reads as "partial"; a shared word reads as
"sufficient"). It is therefore used for two bounded things only: a plain-language coverage note placed in the evidence message, and one focused retrieval retry. A deterministic
abstention is a separate, opt-in step (`abstention`). Its false-gate rate on answerable questions is measured in benchmarks/answer_quality/sufficiency_eval.py before anyone relies on it."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_NAME = re.compile(r"[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")
_NUMBER = re.compile(r"\b\d+(?:[.:]\d+)?\b")

_QUESTION_WORDS = frozenset({
    "what", "which", "who", "whom", "whose", "when", "where", "how", "why", "does", "do", "did", "is", "are", "was", "were", "can", "could", "will", "would", "should",
    "tell", "list", "show", "give", "state", "summarise", "summarize", "explain", "describe",
})
# Words that carry no subject matter on their own. "Notes", "records" and similar name the store, not the thing asked about.
_STOP = frozenset(["a", "an", "the", "and", "or", "but", "if", "of", "in", "on", "at", "to", "for", "from", "by", "with", "about", "into", "over", "than", "as", "is", "are", "was", "were", "be", "been", "being", "am", "do", "does", "did", "has", "have", "had", "having", "it", "its", "this", "that", "these", "those", "there", "here", "i", "me", "my", "mine", "we", "our", "you", "your", "he", "she", "they", "them", "their", "his", "her", "him", "not", "no", "nor", "so", "any", "some", "all", "each", "every", "both", "either", "neither", "more", "most", "much", "many", "few", "other", "another", "such", "only", "own", "same", "too", "very", "just", "also", "then", "now", "still", "yet", "again", "ever", "never", "up", "down", "out", "off", "per", "via", "re", "can", "could", "will", "would", "shall", "should", "may", "might", "must", "tell", "say", "said", "says", "state", "states", "mention", "mentioned", "mentions", "record", "records", "recorded", "note", "notes", "memory", "memories", "according", "anything", "something", "everything", "someone", "anyone", "know", "knew", "known", "think", "see", "seen", "look", "find", "found", "get", "got", "make", "made", "take", "took", "go", "went", "come", "came", "use", "used", "using", "want", "need", "needs", "needed", "let", "like", "please", "thanks", "ask", "asked", "asks", "asking", "want", "wanted", "number"])

_PREFIX = 5


def _stem(word: str) -> str:
    """Crude on purpose: lower-case, drop a possessive, and compare words of five letters or more by their first five letters so retries/retried and owns/owner meet."""
    w = word.lower().removesuffix("'s").removesuffix("’s").strip("'’-")
    for tail in ("ies", "ied", "y"):  # retry / retries / retried meet
        if w.endswith(tail) and len(w) > len(tail) + 2:
            w = w[: -len(tail)] + "i"
            break
    return w if len(w) <= _PREFIX else w[:_PREFIX]


@dataclass(frozen=True)
class Piece:
    """One evidence item as plain data: the text the model will read, its title, and the project scope it belongs to."""

    text: str
    title: str = ""
    scope: str = ""

    @property
    def haystack(self) -> str:
        return f"{self.title}\n{self.scope}\n{self.text}"


@dataclass(frozen=True)
class Assessment:
    verdict: str
    entities: tuple[str, ...] = ()
    aspects: tuple[str, ...] = ()
    absent_entities: tuple[str, ...] = ()
    all_absent: bool = False  # every non-numeric named thing is missing: the evidence is about something else
    uncovered_aspects: tuple[str, ...] = ()
    similar: tuple[str, ...] = ()  # names in the evidence that share a family prefix with an absent one ("Falcon-7B" for "Falcon-3B")
    aspect_titles: tuple[str, ...] = ()  # titles of the items that do hold the aspect (for an entity mismatch)
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def sufficient(self) -> bool:
        return self.verdict == "sufficient"


def question_terms(question: str) -> tuple[list[str], list[str]]:
    """(named things, other content words) of a question. A capitalised word is a name unless it opens the sentence as a question word; numbers count as named things."""
    names: list[str] = []
    aspects: list[str] = []
    seen_first = False
    for m in _WORD.finditer(question):
        w = m.group(0)
        low = w.lower()
        first = not seen_first
        seen_first = True
        if low in _QUESTION_WORDS and (first or not _NAME.fullmatch(w)):
            continue
        bare = w.removesuffix("'s").removesuffix("’s")
        if _NAME.fullmatch(bare) and not (first and low in _STOP) and low not in _STOP and low not in _QUESTION_WORDS:
            if bare not in names:
                names.append(bare)
            continue
        if low in _STOP or low in _QUESTION_WORDS or len(low) < 3:
            continue
        if bare.lower() not in aspects:
            aspects.append(bare.lower())
    for n in _NUMBER.findall(question):
        if n not in names:
            names.append(n)
    return names, aspects


def _mentions(term: str, pieces: Sequence[Piece]) -> list[Piece]:
    if _NUMBER.fullmatch(term) or "-" in term:
        pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
        return [p for p in pieces if pat.search(p.haystack)]
    stem = _stem(term)
    return [p for p in pieces if any(_stem(w) == stem for w in _WORD.findall(p.haystack))]


def _family(name: str) -> str:
    return name.split("-")[0].lower() if "-" in name else ""


def assess(question: str, pieces: Sequence[Piece]) -> Assessment:
    names, aspects = question_terms(question)
    if not pieces:
        return Assessment("none", tuple(names), tuple(aspects))
    # Numbers are candidate values, not subjects: "Is it 45 minutes?" is answered by "no, 30", so a missing number says nothing here.
    named = [n for n in names if not _NUMBER.fullmatch(n)]
    absent = tuple(n for n in named if not _mentions(n, pieces))
    if absent:
        families = {_family(n) for n in absent if _family(n)}
        words = {w for p in pieces for w in _NAME.findall(p.haystack)}
        similar = tuple(sorted({w for w in words if "-" in w and _family(w) in families and w.lower() not in {a.lower() for a in absent}}))
        return Assessment("entity_absent", tuple(names), tuple(aspects), absent_entities=absent, all_absent=len(absent) == len(named), similar=similar)
    # which aspect words does any item hold, and does any item hold an aspect together with a named thing?
    uncovered = tuple(a for a in aspects if not _mentions(a, pieces))
    covered = [a for a in aspects if a not in uncovered]
    if named and covered:
        together = [p for p in pieces if any(p in _mentions(n, pieces) for n in named) and any(p in _mentions(a, pieces) for a in covered)]
        if not together:
            holders = tuple(dict.fromkeys(p.title or p.scope or p.text[:40] for a in covered for p in _mentions(a, pieces)))
            return Assessment("entity_mismatch", tuple(names), tuple(aspects), uncovered_aspects=uncovered, aspect_titles=holders)
    if aspects and not covered:  # the evidence names the thing but holds none of the question's other words ("Harbor" + "on-call", "rotation")
        return Assessment("topic_missing", tuple(names), tuple(aspects), uncovered_aspects=uncovered)
    specific = tuple(a for a in uncovered if any(ch.isdigit() for ch in a))
    if specific:
        return Assessment("partial", tuple(names), tuple(aspects), uncovered_aspects=specific)
    return Assessment("sufficient", tuple(names), tuple(aspects))


def coverage_note(a: Assessment) -> str | None:
    """A short factual line for the evidence message, written by this code and not by any stored text. None when nothing needs saying."""
    if a.verdict == "sufficient":
        return None
    if a.verdict == "none":
        return "Automatic check: no records were found for this question."
    if a.verdict == "entity_absent":
        absent = ", ".join(a.absent_entities)
        extra = f" (the records name {', '.join(a.similar)}, which are different)" if a.similar else ""
        return f"Automatic check: no record below mentions {absent}{extra}."
    if a.verdict == "entity_mismatch":
        named = ", ".join(n for n in a.entities if not _NUMBER.fullmatch(n))
        about = ", ".join(a.aspect_titles[:3])
        return f"Automatic check: no single record below mentions {named} together with the other terms of the question; the records that cover those terms are: {about}."
    if a.verdict in ("partial", "topic_missing"):
        return f"Automatic check: nothing below mentions: {', '.join(a.uncovered_aspects)}."
    return None


def abstention(a: Assessment) -> str | None:
    """A fixed reply for the cases where the evidence plainly does not hold what was asked. Not used unless the caller opts in."""
    if a.verdict == "none":
        return "I don't have anything about that in your records."
    if a.verdict == "entity_absent" and a.all_absent:
        return f"I don't have anything about {', '.join(a.absent_entities)} in your records."
    if a.verdict == "entity_mismatch":
        named = ", ".join(n for n in a.entities if not _NUMBER.fullmatch(n))
        return f"I don't have a record that covers that for {named}. What I do have on the other terms of your question is about something else: {', '.join(a.aspect_titles[:3])}."
    return None


def retry_query(a: Assessment) -> str | None:
    """A focused second query when the first did not cover the question: the named things plus the words no item held. None when a retry cannot help."""
    if a.verdict in ("sufficient", "none"):
        return None
    terms = [*a.entities, *a.uncovered_aspects] if a.verdict != "entity_mismatch" else [*a.entities, *a.aspects]
    return " ".join(dict.fromkeys(terms)) or None


def pieces_from_items(items: Sequence) -> list[Piece]:
    """KnowledgeItems to pieces: the text the builder will show (with a meeting speaker's name), the stored title and the project scope."""
    out = []
    for item in items:
        speaker = item.provenance.speaker
        text = f"{speaker}: {item.text}" if speaker and item.kind == "meeting_segment" else item.text
        out.append(Piece(text=text, title=item.provenance.title or "", scope=item.project_scope or ""))
    return out


__all__ = ["Assessment", "Piece", "abstention", "assess", "coverage_note", "pieces_from_items", "question_terms", "retry_query"]
