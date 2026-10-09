"""C1: proposition- and relationship-aware evidence selection (personal-record questions).

A question is read as a small proposition `(subject, relation, ?)`; candidate evidence (a larger retrieval set than the 10 shown today) is scanned for sentence windows that ASSERT it: the subject (or its
record's title/scope) and an assertion cue of the relation in the same window of at most two sentences, carrying a value of the right kind. Records with an asserting window are `selected`; records that
mention only the subject or only the relation are `related`; the rest are dropped. The result also records every asserted value, so C2 can tell established from conflicted without a model.

Variants (separable): `order` only re-ranks, `filter` shows asserting records plus at most `k_related` related ones. Deterministic and lexical, with a written lexicon (relations.py); when the question's
relation is not in the lexicon the generic path uses the question's own content words as the relation."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from companion_core.knowledge.grounding.relations import (
    HISTORICAL_TEXT,
    HISTORICAL_TITLE,
    HISTORY_QUESTION,
    NUMBER_WORDS,
    RELATIONS,
    STRUCTURED,
)
from companion_core.knowledge.sufficiency import (
    _NUMBER,
    _WORD,
    Piece,
    _stem,
    question_terms,
)
from companion_core.knowledge.sufficiency_section import _descriptors, passages

_CALENDAR = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_NAME = re.compile(r"\b[A-Z][a-z']+(?: [A-Z][a-z']+)?\b")
_MODEL = re.compile(r"\b[A-Z][a-z]+-\d+B\b")
_HOST = re.compile(r"\b(?:GPU|CPU|edge|batch) host\b", re.IGNORECASE)
_HOURS = re.compile(r"\b\d{1,2} to \d{1,2}\b")
_NUM = re.compile(r"\b\d+\b")
_CLAUSE_SPLIT = re.compile(r",? and (?=(?:what|who|how|which|when|where|whose)\b)|, and |\band (?=what\b)", re.IGNORECASE)


@dataclass(frozen=True)
class Proposition:
    subjects: tuple[str, ...]
    relation: str | None  # a key of RELATIONS, or None for the generic path
    cues: tuple[str, ...]  # the words that mark an assertion (relation cues, or the question's content words on the generic path)
    value_kind: str
    structured: bool = False  # answered from an authoritative store (C3); C1 and C2 do not judge it


@dataclass
class Assertion:
    item_index: int
    unit: str
    values: tuple[str, ...]
    historical: bool = False


@dataclass
class Selection:
    propositions: list[Proposition]
    assertions: list[list[Assertion]]  # per proposition (clause)
    selected: list[int] = field(default_factory=list)  # indices into the candidate list, best first
    related: list[int] = field(default_factory=list)
    other_subject_assertions: list[int] = field(default_factory=list)  # per clause: how many assertions of the relation were about a different subject
    absent_qualifiers: list[list[str]] = field(default_factory=list)  # per clause: discriminating question words found in no candidate sentence
    history: bool = False  # the question asks about an earlier state


def _stems(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text)]


def _has_cue(haystack: str, cues: Sequence[str], *, modifiers_count: bool = True) -> bool:
    low = haystack.lower()
    if not modifiers_count:  # a cue word in the possessive ("the Cedar lead's vacation") modifies the next noun; it is not the relation asked about
        low = re.sub(r"\b\w+['’]s\b", " ", low)
        haystack = re.sub(r"\b\w+['’]s\b", " ", haystack)
    words = set(_stems(haystack))
    for cue in cues:
        if " " in cue:
            if cue in low:
                return True
        elif _stem(cue) in words:
            return True
    return False


def read_question(question: str, known_people: Sequence[str] = ()) -> list[Proposition]:
    """One proposition per clause; a clause without its own subject inherits the first clause's."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(question) if c and c.strip()] or [question]
    props: list[Proposition] = []
    inherited: tuple[str, ...] = ()
    for clause in clauses:
        names, aspects = question_terms(clause)
        # adjacent capitalised tokens form one person: "Amara Osei"
        subjects = tuple(n for n in names if not _NUMBER.fullmatch(n) and n.lower() not in _CALENDAR)
        if not subjects:
            subjects = inherited
        else:
            inherited = inherited or subjects
        relation = None
        if any(_has_cue(clause, spec["question"]) for spec in STRUCTURED.values()):
            props.append(Proposition(subjects, "attends", (), "text", structured=True))
            continue
        best = 0
        for rel, spec in RELATIONS.items():  # the relation with the most (and most specific) question cues wins
            hits = [c for c in spec["question"] if _has_cue(clause, [c], modifiers_count=False)]
            score = sum(2 if " " in c else 1 for c in hits)
            if score > best:
                best, relation = score, rel
        if relation:
            spec = RELATIONS[relation]
            props.append(Proposition(subjects, relation, tuple(spec["assertion"]), spec["value"]))
        else:
            props.append(Proposition(subjects, None, tuple(a for a in aspects if a not in {s.lower() for s in subjects}), "text"))
    return props


def values_in(text: str, kind: str, known_people: Sequence[str]) -> tuple[str, ...]:
    if kind == "person":
        found = [p for p in known_people if p.lower() in text.lower() or p.split()[0].lower() in text.lower().split()]
        return tuple(dict.fromkeys(found))
    if kind == "number":
        nums = {m.group(0) for m in _NUM.finditer(text)}
        nums |= {str(NUMBER_WORDS[w]) for w in re.findall(r"[a-z]+", text.lower()) if w in NUMBER_WORDS}
        return tuple(sorted(nums))
    if kind == "model":
        return tuple(dict.fromkeys(m.group(0) for m in _MODEL.finditer(text)))
    if kind == "host":
        return tuple(dict.fromkeys(m.group(0).lower() for m in _HOST.finditer(text)))
    if kind == "hours":
        return tuple(dict.fromkeys(m.group(0) for m in _HOURS.finditer(text)))
    return tuple(dict.fromkeys(m.group(0) for m in _NAME.finditer(text) if m.group(0) not in {"The", "A", "An", "Jobs", "Interactive", "Roll", "Deploy"})) or tuple(_NUM.findall(text))


def _subject_in(unit_hay: str, subjects: Sequence[str]) -> bool:
    low = unit_hay.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(s.lower())}", low) for s in subjects)


GENERIC = frozenset(["times", "many", "long", "often", "much", "failed", "job", "jobs", "one", "big", "large", "next", "last", "this", "current", "new", "old", "also", "main", "whole", "entire"])


@dataclass(frozen=True)
class Unit:
    sentence: str  # where the relation cue, the value and any qualifier must co-occur
    window: str  # context + previous sentence + sentence: where the subject may be found
    context: str = ""  # the record's title, heading and scope
    scope: str = ""
    historical: bool = False


def _units(piece: Piece) -> list[Unit]:
    ps = passages(piece)
    ctx = f"{piece.title} {piece.scope}"
    out = []
    for i, p in enumerate(ps):
        prev = ps[i - 1].text if i else ""
        low = p.text.lower()
        hist = any(h in low for h in HISTORICAL_TEXT) or any(h in f"{piece.title}".lower() for h in HISTORICAL_TITLE)
        out.append(Unit(p.text, f"{ctx} {p.title} {prev} {p.text}", f"{ctx} {p.title}", piece.scope or "", hist))
    return out


def _qualifiers(prop: Proposition, question_clause_aspects: Sequence[str], df: dict[str, float]) -> list[str]:
    """Question words beyond the subject and the relation that DISCRIMINATE among the candidates (present in some but fewer than 35% of the candidate sentences). They must co-occur with the value."""
    cue_stems = {_stem(w) for c in prop.cues for w in c.split()}
    subj = {_stem(s) for s in prop.subjects}
    out = []
    for a in question_clause_aspects:
        st = _stem(a)
        if st in cue_stems or st in subj or a in GENERIC:
            continue
        if 0 < df.get(st, 0.0) < 0.35:
            out.append(st)
    return out


def select(question: str, pieces: Sequence[Piece], *, known_people: Sequence[str] = (), skip: Collection[int] = (), max_selected: int = 6, strict_qualifiers: bool = False, alias_scopes: bool = True) -> Selection:
    props = read_question(question, known_people)
    clause_aspects = [question_terms(c)[1] for c in ([c.strip() for c in _CLAUSE_SPLIT.split(question) if c and c.strip()] or [question])]
    history = any(h in question.lower() for h in HISTORY_QUESTION)
    units_by_item = {idx: _units(piece) for idx, piece in enumerate(pieces) if idx not in skip}
    all_sentences = [u.sentence for us in units_by_item.values() for u in us]
    df: dict[str, float] = {}
    if all_sentences:
        counts: dict[str, int] = {}
        for sent in all_sentences:
            for st in set(_stems(sent)):
                counts[st] = counts.get(st, 0) + 1
        df = {st: n / len(all_sentences) for st, n in counts.items()}
    asserts: list[list[Assertion]] = [[] for _ in props]
    other_subject = [0] * len(props)
    absent_q: list[list[str]] = [[] for _ in props]
    subject_only: set[int] = set()
    cue_only: set[int] = set()
    asserting_items: dict[int, int] = {}
    for ci, prop in enumerate(props):
        if prop.structured:
            continue
        subjects = list(prop.subjects)
        if alias_scopes and subjects:  # a project scope that co-occurs with the subject in a record is an alias of it for this query ("Ferry queue" and the project it belongs to)
            for us in units_by_item.values():
                for u in us:
                    if u.scope and _subject_in(u.window, prop.subjects) and u.scope not in (s.lower() for s in subjects):
                        subjects.append(u.scope)
        subjects = tuple(dict.fromkeys(subjects))
        aspects = clause_aspects[min(ci, len(clause_aspects) - 1)]
        cue_stems = {_stem(w) for c in prop.cues for w in c.split()}
        subj_stems = {_stem(x) for x in prop.subjects} | {_stem(d) for d in _descriptors(question, list(prop.subjects))}  # "Ferry QUEUE": the word after a name belongs to the name
        quals = []
        for a_ in aspects:
            st = _stem(a_)
            if st in cue_stems or st in subj_stems or a_ in GENERIC:
                continue
            if 0 < df.get(st, 0.0) < 0.35:
                quals.append(st)
            elif df.get(st, 0.0) == 0.0 and prop.relation is None or (df.get(st, 0.0) == 0.0 and strict_qualifiers):
                absent_q[ci].append(st)
        for idx, units in units_by_item.items():
            for u in units:
                other_actor = any(p.lower() in u.sentence.lower() and not _subject_in(p, prop.subjects) for p in known_people)
                has_subject = bool(subjects) and _subject_in(u.sentence if other_actor else u.window, subjects)
                if prop.relation:
                    cue = _has_cue(u.sentence, prop.cues)
                else:
                    cue = bool(prop.cues) and all(_stem(c) in set(_stems(u.sentence)) for c in prop.cues)
                sent_stems = set(_stems(u.window))  # a qualifier may sit in the sentence, the previous sentence or the record context, but not in the NEXT sentence
                qual_ok = all(q in sent_stems for q in quals)
                vals = values_in(u.sentence, prop.value_kind, known_people) if cue else ()
                if has_subject and cue and vals and qual_ok and not (absent_q[ci] and strict_qualifiers):
                    asserts[ci].append(Assertion(idx, u.sentence, vals, u.historical))
                    asserting_items[idx] = asserting_items.get(idx, 0) + 1
                elif cue and vals and not has_subject and qual_ok:
                    other_subject[ci] += 1
                    cue_only.add(idx)
                elif has_subject:
                    subject_only.add(idx)
    selected = sorted(asserting_items, key=lambda i: (-asserting_items[i], i))[:max_selected]
    related = [i for i in sorted(subject_only | cue_only) if i not in asserting_items]
    return Selection(props, asserts, selected, related, other_subject, absent_q, history)


def reorder(items: Sequence, sel: Selection, variant: str, *, k_related: int = 2, limit: int = 10) -> list:
    """`order`: asserting records first, everything else after in the original order. `filter`: asserting records plus at most `k_related` related ones (and, when nothing asserts, the top related ones)."""
    chosen = list(sel.selected)
    if variant == "order":
        rest = [i for i in range(len(items)) if i not in chosen]
        return [items[i] for i in (chosen + rest)[:limit]]
    extra = [i for i in sel.related if i not in chosen][: (k_related if chosen else max(k_related, 3))]
    return [items[i] for i in chosen + extra][:limit]
