"""Question-side decomposition for the deterministic path (Phase 44, I-2 follow-up, 2026-10-10). Question text -> typed components, with NO model call and no gold.

A question is split into clauses; each clause is typed against the registry (registry.py) as a subject (a typed entity mention whose type the relation accepts), a relation (its question cues), an ask (value /
existence / ordering) and a time qualification (any / current / past, plus a stated month). A clause that cannot be typed UNAMBIGUOUSLY is not guessed: it becomes an untyped component with a reason code, the
reply says only that this part was not worked out, and the remaining clauses are answered. Reasons are the audit trail of every refusal to invent a structure:

    pronoun_reference, no_relation_cue, ambiguous_relation, subject_type_mismatch, ambiguous_subject, no_subject, unexplained_entity, value_in_question, answer_type_mismatch, existence_mismatch, unsupported_period,
    unsupported_qualifier, weak_ordering_cue, conflicting_time_cues, unsupported_question_type, not_a_question_clause

Conservative by design: a recognised question form is required (a wh-word or an auxiliary opener) unless the fragment is a bare continuation of a typed neighbour (a second subject for the same relation, or a second
relation for the same subject). The labelled development set `selective/decomposition_dev_set.json` measures it; it is a development set, not an acceptance set."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime

from companion_core.knowledge.answerability_b1.admission import AdmissionPolicy
from companion_core.knowledge.answerability_b1.contract import Plan, build_plan
from companion_core.knowledge.answerability_b1.registry import (
    EntityType,
    Mention,
    Registry,
    RelationDef,
)
from companion_core.knowledge.answerability_b1.types import (
    Ask,
    AuthDecision,
    Component,
    DiscoveryItem,
    Scope,
)

P = EntityType
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"

_PREAMBLE = re.compile(r"^\s*(?:(?:could|can|would|will) you (?:please )?(?:tell|show|let) me|(?:could|can|would) you (?:please )?(?:say|tell)|please (?:tell|say|show) me|tell me|show me|please say|please|"
                       r"i(?:'d| would) like to know|i want to know|i need to know|do you know|i(?:'m| am) wondering|(?:also|and|then|so|well|okay|ok)\b)\s*[,:]?\s*", re.IGNORECASE)
_SPLIT = re.compile(r"\s*;\s*|\s*,?\s*\bas well as\s+|\s*,?\s+(?:and|or)\s+(?:also\s+)?|\s*,\s*(?:also\s+)?", re.IGNORECASE)
_WH = re.compile(r"\b(?:who|whom|whose|what|which|when|where|why|how)\b", re.IGNORECASE)
_AUX_OPEN = re.compile(r"^\s*(?:is|are|was|were|does|do|did|has|have|had|can|could|will|would|should|shall)\b", re.IGNORECASE)
_PRONOUN = re.compile(r"\b(?:it|its|it's|they|them|their|theirs|he|she|him|his|hers|itself|themselves)\b|\b(?:that|this|those|these)\s+(?:project|one|ones|system|service|queue|team|thing|model|host|meeting)s?\b|\bthe same\b", re.IGNORECASE)

_PAST = re.compile(r"\b(?:old|previous|previously|formerly|used to|earlier|archived|originally|back then|at the time)\b", re.IGNORECASE)
_CURRENT = re.compile(r"\b(?:now|currently|current|today|at present|right now|at the moment|these days)\b", re.IGNORECASE)
_PERIOD = re.compile(rf"\b(in|before|as of)\s+({_MONTHS})\b", re.IGNORECASE)
_BAD_PERIOD = re.compile(rf"\b(?:after|since|until|till|during|between|from)\s+(?:the\s+)?(?:{_MONTHS})\b|\b(?:19|20)\d\d\b|\b(?:this|last|next|past|previous)\s+(?:week|month|year|quarter|sprint|{_DAYS})\b|"
                         r"\b(?:yesterday|tomorrow|tonight|ago|recently|lately|earlier today)\b|\bq[1-4]\b|\b(?:summer|winter|spring|autumn)\b", re.IGNORECASE)
_NEXT = re.compile(r"\bnext\b", re.IGNORECASE)
_MONTH_NAME = re.compile(rf"\b(?:{_MONTHS})\b", re.IGNORECASE)
_DAY_NAME = re.compile(rf"\b(?:{_DAYS})\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")

_ORDER_STRONG = re.compile(r"\b(?:updated|replaced|superseded|overrid(?:den|es|e)|newer|older|more recent|changed|came first|after the other|before the other)\b", re.IGNORECASE)
_ORDER_WEAK = re.compile(r"\b(?:latest|newest|most recent|last updated)\b", re.IGNORECASE)
_EXISTENCE = re.compile(r"\b(?:is|are) there\b|\b(?:does|do|did)\b.+?\bhave\s+(?:an?|any|some)\b|\bhas\b.+?\b(?:got|an?)\b", re.IGNORECASE)

# What a wh-phrase asks for, mapped to the answer kinds of RelationDef.asks(). Earlier entries win.
_WH_KINDS: tuple[tuple[re.Pattern, frozenset[str]], ...] = tuple((re.compile(p, re.IGNORECASE), frozenset(k.split())) for p, k in (
    (r"\bwho(?:m|se)?\b|\bwhich (?:person|people|engineer|engineers)\b", "person"),
    (r"\b(?:until|through|by) (?:which month|when)\b|\bwhich month\b|\bwhat month\b", "month day"),
    (r"\bwhat hours\b|\bwhich hours\b", "hours time"),
    (r"\bwhat time\b|\bwhich time\b|\bat what time\b", "time hours"),
    (r"\bwhich day\b|\bwhat day\b|\bon which day\b", "day"),
    (r"\bwhich model\b|\bwhat model\b", "model text"),
    (r"\bwhich (?:host|machine)\b|\bwhat (?:host|machine|hardware)\b|\bon which (?:host|machine)\b", "host"),
    (r"\bhow (?:many|much|long|large|big|often)\b", "number"),
    (r"\bwhen\b", "month day time hours"),
    (r"\bwhere\b", "host"),
))


@dataclass(frozen=True)
class Clause:
    index: int
    text: str
    component: Component | None  # None: the clause could not be typed
    reason: str = ""  # why not (a code above); "" for a typed clause
    mention: Mention | None = None  # the subject mention, for inheritance by a continuation fragment


@dataclass(frozen=True)
class Decomposition:
    question: str
    clauses: tuple[Clause, ...]
    mentions: tuple[Mention, ...]  # every entity named anywhere in the question

    @property
    def components(self) -> tuple[Component, ...]:
        return tuple(c.component if c.component is not None else Component(f"c{c.index}", "", (), None) for c in self.clauses)

    @property
    def typed(self) -> tuple[Component, ...]:
        return tuple(c.component for c in self.clauses if c.component is not None)

    @property
    def uncertain(self) -> tuple[Clause, ...]:
        return tuple(c for c in self.clauses if c.component is None)

    @property
    def fallback(self) -> bool:
        """True when ANY clause could not be typed (that clause is withheld; the others are still answered)."""
        return any(c.component is None for c in self.clauses) or not self.clauses

    @property
    def all_uncertain(self) -> bool:
        return not any(c.component is not None for c in self.clauses)


_REQUEST = re.compile(r"\b(?:tell|show|let) me\b|\bplease (?:say|tell|show)\b|\bi(?:'d| would) like to know\b|\bi (?:want|need) to know\b|\bdo you know\b|\bwondering\b|\bsay\b", re.IGNORECASE)


def _strip_preamble(text: str) -> tuple[str, bool]:
    """Remove polite openers ("could you tell me ..."). The flag says a request opener was removed, so what remains is an indirect question even without a wh-word ("... Harbor's default model")."""
    prev = None
    requested = False
    while prev != text:
        prev = text
        m = _PREAMBLE.match(text)
        if m and _REQUEST.search(m.group(0)):
            requested = True
        text = _PREAMBLE.sub("", text, count=1)
    return text.strip(), requested


def _wh_kinds(text: str) -> frozenset[str] | None:
    for pat, kinds in _WH_KINDS:
        if pat.search(text):
            return kinds
    return None


def _spans(patterns: tuple[str, ...], text: str) -> list[tuple[int, int]]:
    return [m.span() for p in patterns for m in re.finditer(p, text, re.IGNORECASE)]


def _contained(inner: list[tuple[int, int]], outer: list[tuple[int, int]]) -> bool:
    return bool(inner) and all(any(a >= x and b <= y and (b - a) < (y - x) for x, y in outer) for a, b in inner)


def _pure_mention(text: str, mention: Mention) -> bool:
    """A fragment that is only an entity (with an optional article or possessive): a second subject for the previous clause's relation."""
    rest = (text[: mention.start] + text[mention.end:]).strip()
    return bool(re.fullmatch(r"(?:the|a|an|'s|’s|\s)*", rest, re.IGNORECASE))


def _period_of(low: str) -> tuple[tuple[str, str] | None, str]:
    m = _PERIOD.search(low)
    if not m:
        return None, low
    return (m.group(1).lower(), m.group(2).lower()), low[: m.start()] + " " + low[m.end():]


def _type_fragment(text: str, registry: Registry, prev: Clause | None, index: int, requested: bool = False) -> Clause:
    def no(reason: str) -> Clause:
        return Clause(index, text, None, reason)

    mentions = registry.entities.mentions(text)
    question_form = bool(_WH.search(text) or _AUX_OPEN.match(text) or requested)
    if re.search(r"\bwhy\b", text, re.IGNORECASE):
        return no("unsupported_question_type")
    if _PRONOUN.search(text):
        return no("pronoun_reference")

    # --- relation candidates: question cues, longest phrase wins over a phrase it contains, then the entity types decide
    cand: dict[str, list[tuple[int, int]]] = {}
    for r in registry.relations:
        spans = _spans(r.qcues, text)
        if spans:
            cand[r.name] = spans
    names = list(cand)
    for a in names:
        for b in names:
            if a != b and a in cand and b in cand and _contained(cand[a], cand[b]):
                del cand[a]
    for r in registry.relations:  # the role-holder rule: "the Marlin lead ... away" asks about the lead's days off; the word "lead" there is only the role
        role = r.holder_role
        if role and r.name in cand and role in cand:
            role_spans = []
            for m in mentions:
                after = re.match(rf"(?:'s|’s)?\s*{role}\b", text[m.end:], re.IGNORECASE)
                if after:
                    role_spans.append((m.start, m.end + after.end()))
                of = re.search(rf"\b{role}\s+of\s+{re.escape(m.subject)}\b", text, re.IGNORECASE)
                if of:
                    role_spans.append(of.span())
            if all(any(a >= x and b <= y for x, y in role_spans) for a, b in cand[role]):
                del cand[role]
    rels = [registry.relation(n) for n in cand]
    assert all(r is not None for r in rels)

    if not rels:
        # continuation: a bare entity continues the previous clause's relation ("... the Ember API and the Kiln scheduler")
        if prev and prev.component and prev.component.relation and not _WH.search(text) and len(mentions) == 1 and _pure_mention(text, mentions[0]):
            pr = registry.relation(prev.component.relation)
            if pr and mentions[0].as_type(pr.subject_types):
                m = mentions[0]
                c = prev.component
                return Clause(index, text, Component(f"c{index}", m.subject, (m.alias,), pr.name, c.ask, c.scope, registry.label(pr.name, m), c.period), "", m)
        return no("no_relation_cue" if question_form or mentions else "not_a_question_clause")

    # --- the entity types decide between candidate relations
    viable = [r for r in rels if any(m.as_type(r.subject_types) for m in mentions)]
    carried = None
    if not viable and not mentions and not _WH.search(text) and prev and prev.mention and prev.component:
        viable = [r for r in rels if prev.mention.as_type(r.subject_types)]
        carried = prev.mention  # a bare relation continues the previous clause's subject ("Harbor's default model and rollback window")
    if not viable:
        return no("subject_type_mismatch" if mentions else "no_subject")
    if len(viable) > 1:
        return no("ambiguous_relation")
    rel: RelationDef = viable[0]
    if not question_form and carried is None:
        return no("not_a_question_clause")

    eligible = [carried] if carried else [m for m in mentions if m.as_type(rel.subject_types)]
    if len({m.subject.casefold() for m in eligible}) != 1:
        return no("ambiguous_subject")
    subject = eligible[0]
    others = [m for m in mentions if m is not subject and m.subject.casefold() != subject.subject.casefold()]
    if others:
        return no("value_in_question" if any(m.types & rel.value_types for m in others) else "unexplained_entity")

    # --- time qualification
    low = text
    period, low = _period_of(low)
    if _BAD_PERIOD.search(low) or (_NEXT.search(low) and not rel.allows_next):
        return no("unsupported_period")
    if _MONTH_NAME.search(low) or _DAY_NAME.search(low):
        return no("unsupported_qualifier")
    past, current = bool(_PAST.search(low)) or period is not None, bool(_CURRENT.search(low))
    if past and current:
        return no("conflicting_time_cues")
    scope = Scope.PAST if past else Scope.CURRENT if current else Scope.ANY

    # --- a literal value in the question (a number) is a request to verify it, not to look it up
    masked = low
    for m in mentions:
        masked = masked.replace(text[m.start:m.end], " ")
    if _NUMBER.search(masked):
        return no("value_in_question")

    # --- what kind of answer the wh-phrase asks for must be something the relation can give
    wh = _wh_kinds(text)
    if wh is not None and not (wh & rel.asks()) and not (rel.existence):
        return no("answer_type_mismatch")

    # --- the ask
    existence = bool(_EXISTENCE.search(text))
    if _ORDER_WEAK.search(text):
        return no("weak_ordering_cue")
    if rel.existence:
        if not existence or _ORDER_STRONG.search(text):
            return no("existence_mismatch")
        ask = Ask.EXISTENCE
    else:
        if existence:
            return no("existence_mismatch")
        ask = Ask.ORDERING if _ORDER_STRONG.search(text) else Ask.VALUE
    return Clause(index, text, Component(f"c{index}", subject.subject, (subject.alias,), rel.name, ask, scope, registry.label(rel.name, subject), period if scope is Scope.PAST else None), "", subject)


def _fragments(question: str) -> list[tuple[str, bool]]:
    """(fragment, requested): `requested` is True when the sentence opened with a polite request ("could you tell me ..."), which makes even a bare noun phrase an indirect question."""
    out: list[tuple[str, bool]] = []
    for sentence in re.split(r"(?<=[?.!])\s+|\n+", question.strip()):
        sentence, requested = _strip_preamble(sentence.strip().rstrip("?.!").strip())
        if not sentence:
            continue
        frags = [f.strip() for f in _SPLIT.split(sentence) if f and f.strip()]
        merged: list[str] = []
        carry = ""
        for f in frags:
            f = f"{carry} {f}".strip() if carry else f
            carry = ""
            only_time = bool(_PERIOD.fullmatch(f.strip()) or _CURRENT.fullmatch(f.strip()) or _PAST.fullmatch(f.strip()))  # a fronted time phrase belongs to the clause that follows it
            if only_time:
                carry = f
                continue
            stripped, _ = _strip_preamble(f)
            if stripped:
                merged.append(stripped)
        if carry:
            merged.append(carry)
        out.extend((m, requested) for m in merged)
    return out


def decompose_question(question: str, registry: Registry) -> Decomposition:
    """Deterministic split and typing. Never raises on odd input; a clause it cannot type is returned untyped with a reason."""
    text = re.sub(r"\s+", " ", question or "").strip()
    clauses: list[Clause] = []
    for n, (frag, requested) in enumerate(_fragments(text), 1):
        clauses.append(_type_fragment(frag, registry, clauses[-1] if clauses else None, n, requested))
    seen = registry.entities.mentions(text)
    return Decomposition(text, tuple(clauses), tuple(seen))


def plan_question(question: str, registry: Registry, items: Collection[DiscoveryItem], auths: Mapping[str, AuthDecision], *, now: datetime, eids: Mapping[str, str], policy: AdmissionPolicy,
                  structured: Collection = (), pool_mentions: Collection[Mention] | None = None) -> tuple[Plan, Decomposition]:
    """End to end for one question: decompose, give every component the competing subjects its relation's types allow (the entities of the record pool plus the ones the question names), then the normal
    admission / state / contract pipeline. `pool_mentions` may be passed pre-harvested to avoid re-reading the pool for every question."""
    dec = decompose_question(question, registry)
    pool = list(pool_mentions) if pool_mentions is not None else registry.entities.harvest([*(i.text for i in items), *(getattr(s, "title", "") for s in structured)])
    full = [*pool, *dec.mentions]

    def known(component: Component) -> list[str]:
        return registry.competitors(component.relation, component.aliases, full) if component.relation else []

    plan = build_plan(dec.components, items, auths, now=now, specs=registry.specs(), eids=eids, known_subjects=known, policy=policy, fallback=dec.fallback, structured=structured)
    return plan, dec
