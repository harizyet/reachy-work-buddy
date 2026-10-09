"""Which chat turns count as knowledge questions for the shadow evaluation (Phase 44E follow-up).

The shadow's promotion criterion is "at least 50 qualifying knowledge queries over at least 14 days", so what qualifies must be defined before any
count means anything. A turn qualifies when all three hold, by fixed rules (no model, no retrieval result, so a question about something the records
lack still qualifies and shows up as a miss rather than disappearing):

1. it is information-seeking: a question, or a "list/show/tell me what" request;
2. it is anchored to the owner's own records: first-person record words (my, our, we decided, did I), a record noun (task, reminder, note, meeting, sync,
   document, action item ...), or a term from the owner's records (a title, a person or project name) supplied by the caller;
3. it is not an action request (add, delete, mark, set, turn on, call, send, play ...), a greeting or acknowledgement, or a general-knowledge or
   world question (time, weather, news).

The result carries the reasons, never the text, so it can be counted and audited. The rules were built on a development set and checked once on a
separate test set (benchmarks/answer_quality/qualify_cases.json); the figures are in docs/verification/phase-44e-qualification-2026-10-10.md.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

_QUESTION_START = re.compile(
    r"^\s*(?:what|what's|whats|who|who's|whom|whose|when|when's|where|where's|which|how|why|is|are|was|were|do|does|did|has|have|had|can|could|will|would|should|"
    r"list|show|tell me|remind me (?:what|when|who|where|how|which|about)|find|look up|search|give me|read me|summari[sz]e my)\b", re.IGNORECASE)
_ANCHOR_PHRASE = re.compile(
    r"\b(?:my|mine|our|we|we've|we'd|i've|i'd|did i|do i have|do i need|what do i|have i|had i|am i|i (?:noted|wrote|decided|said|asked|saved|recorded|promised|set)|"
    r"last (?:week|time|meeting)|yesterday|this week|the (?:weekly|daily|planning|team|project|review))\b", re.IGNORECASE)
_RECORD_NOUN = re.compile(
    r"\b(?:tasks?|to-?dos?|to do list|reminders?|notes?|memos?|meetings?|syncs?|reviews?|documents?|docs?|meeting minutes|transcripts?|action items?|follow-?ups?|"
    r"postmortems?|runbooks?|checklists?|memor(?:y|ies)|calendar|appointments?|emails?|drafts?|outstanding|overdue)\b", re.IGNORECASE)
_ACTION_START = re.compile(
    r"^\s*(?:please\s+)?(?:add|create|make|delete|remove|clear|cancel|mark|complete|finish|set|turn|switch|enable|disable|call|phone|send|email|text|play|stop|pause|"
    r"open|close|start|stand|sit|wave|move|dance|sing|write|draft|translate|explain|define|recommend|pretend|summari[sz]e (?:this|the following)|calculate|compute|"
    r"remind me to|remember (?:that|to)|forget|update|change|rename|schedule|book)\b", re.IGNORECASE)
_SMALLTALK = re.compile(
    r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening|night)|thanks?(?: you)?|thank you|ok(?:ay)?|cool|great|bye|goodbye|how are you(?: today)?|who are you|"
    r"i'?m (?:tired|bored|fine|ok)|what'?s up)\b[\s.!,]*", re.IGNORECASE)
_WORLD = re.compile(
    r"\b(?:weather|forecast|rain|news|headlines|what time is it|what day is it|what'?s the date|capital of|speed of light|tallest|how tall|stand for|"
    r"world cup|who painted|who wrote the|who won|recipe|joke|poem|haiku|python|machine learning|entropy|photosynthesis|interesting)\b", re.IGNORECASE)
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b")


@dataclass(frozen=True)
class Qualification:
    qualifies: bool
    reasons: tuple[str, ...]  # categories only, e.g. ("question", "record_noun")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9-]{2,}", re.sub(r"'s\b", "", text.lower())))


def qualify(text: str, *, known_terms: Collection[str] = (), slash_command: bool = False) -> Qualification:
    """Whether a chat turn is a knowledge question. `known_terms` are lowercase words from the owner's records (titles, people, projects)."""
    stripped = text.strip()
    if slash_command or not stripped or stripped.startswith("/"):
        return Qualification(False, ("command",))
    if _SMALLTALK.match(stripped) and len(stripped.split()) <= 5:
        return Qualification(False, ("smalltalk",))
    if _ACTION_START.match(stripped):
        return Qualification(False, ("action_request",))
    shaped = bool(_QUESTION_START.match(stripped)) or stripped.endswith("?")
    if not shaped:
        return Qualification(False, ("not_a_question",))
    reasons = ["question"]
    anchors = []
    if _ANCHOR_PHRASE.search(stripped):
        anchors.append("first_person_or_team")
    if _RECORD_NOUN.search(stripped):
        anchors.append("record_noun")
    known = _words(stripped) & {t.lower() for t in known_terms}
    if known:
        anchors.append("known_term")
    elif known_terms and _PROPER.search(stripped) and not anchors:
        pass  # a capitalised word that is not in the records (France, Python) is not an anchor
    if _WORLD.search(stripped) and not anchors:
        return Qualification(False, ("world_question",))
    if not anchors:
        return Qualification(False, ("question_without_record_anchor",))
    return Qualification(True, tuple(reasons + anchors))


def vocabulary_from_texts(texts: Collection[str], *, stop: Collection[str] = (), limit: int = 5000) -> frozenset[str]:
    """Lowercase content words of record titles and names, for `known_terms`. Capped; callers refresh it on a timer, never per query."""
    words: set[str] = set()
    for text in texts:
        words |= {w for w in _words(text) if len(w) >= 4 and w not in stop}
        if len(words) >= limit:
            break
    return frozenset(words)


_COMMON = {"about", "after", "again", "always", "because", "before", "being", "could", "every", "first", "found", "great", "other", "should", "still", "their", "there", "these", "thing", "things", "those", "through", "under", "until", "using", "where", "which", "while", "would", "write"}


async def build_vocabulary(adapters: dict, *, max_sources: int = 2000, max_records_per_term: int = 3) -> frozenset[str]:
    """Known terms from the owner's own records, read through the source adapters: every title and name, plus content words that occur in at most
    `max_records_per_term` records (specific enough to anchor a question; frequent words like "time" would let world questions through). Records of the
    sensitive tier contribute nothing. Capped; the shadow refreshes it on a timer inside its own worker, never on the request path. Returns words only."""
    from collections import Counter

    from shared.models.response import Privacy

    titles: list[str] = []
    document_frequency: Counter = Counter()
    seen = 0
    for adapter in adapters.values():
        for source_id in await adapter.list_ids():
            if seen >= max_sources:
                break
            seen += 1
            state = await adapter.state(source_id)
            if state.status != "visible":
                continue
            items = [i for i in state.items if i.sensitivity != Privacy.SENSITIVE]
            titles += [i.title for i in items if getattr(i, "title", None)]
            words: set[str] = set()
            for item in items:
                words |= {w for w in _words(item.text) if len(w) >= 5 and w not in _COMMON}
            document_frequency.update(words)
    rare = {w for w, n in document_frequency.items() if n <= max_records_per_term}
    return frozenset(rare | set(vocabulary_from_texts(titles, stop=_COMMON)))


__all__ = ["Qualification", "build_vocabulary", "qualify", "vocabulary_from_texts"]
