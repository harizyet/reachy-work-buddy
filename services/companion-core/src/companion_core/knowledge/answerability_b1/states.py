"""Per-claim answerability: a pure function from the admitted facts for ONE component to one of seven states. One component's ticket never depends on another's.

Rules (Stage B design section 3). Time: only a record's explicit wording or explicit effective period says when a fact holds. Retrieval time and record creation time are not inputs here (they are not even
on the admitted fact's decision path), so neither can establish recency or supersession.

  VALUE   facts in scope  -> one value SUPPORTED | several values CONFLICTED (unless an explicit authoritative supersession removes the older) | only past facts for a current question, or a past
          question answered by past facts -> HISTORICAL | nothing in scope -> UNSUPPORTED
  EXISTENCE  negating fact only -> NEGATIVE_SUPPORTED | asserting fact only -> SUPPORTED | both -> CONFLICTED | neither -> NEGATIVE_UNSUPPORTED (never "does not exist")
  ORDERING   explicit authoritative supersession, or two authoritative facts with explicit and different effective starts -> SUPPORTED with the stated basis | otherwise ORDER_UNSUPPORTED, keeping the values
Ambiguous, unreadable or unauthorised records contribute nothing; an ambiguous record that touches the same subject and relation is reported on the ticket so the reply can say so."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field, replace

from companion_core.knowledge.answerability_b1 import transitions
from companion_core.knowledge.answerability_b1.admission import AdmissionResult
from companion_core.knowledge.answerability_b1.types import (
    AUTHORITATIVE,
    AdmittedFact,
    Ask,
    Component,
    FactScope,
    Scope,
    ScopedFinding,
    State,
)


@dataclass(frozen=True)
class Ticket:
    component: Component
    state: State
    reasons: tuple[str, ...]
    values: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (value, supporting refs): the only things a reply may assert for this component
    history: tuple[tuple[str, tuple[str, ...]], ...] = ()  # past values shown as past
    ambiguous_refs: tuple[str, ...] = ()
    ordering_basis: str | None = None
    # rubric v5. `scoped`: verifiable bounded-search negatives (reported as search results, never as absence). `absence_authors`: author classes of non-authoritative records that say "there is no X"
    # (reported as an attributed statement the records do not establish). Both only ever appear on a NEGATIVE_UNSUPPORTED existence ticket.
    scoped: tuple[ScopedFinding, ...] = ()
    absence_authors: tuple[str, ...] = ()
    # explicit value transitions (transitions.py). `pending`: (value, status, refs) the records report as DECIDED or PLANNED, never as the value in effect. `out_of_use`: values stated retired or rolled back; they are never
    # answered, they only make a competing live claim unsafe to state. `time_phrase`: the record's own relative-time wording ("this month"), kept in the reply when every supporting record carries the same one.
    pending: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    out_of_use: tuple[tuple[str, tuple[str, ...]], ...] = ()
    time_phrase: str = ""
    # discovery-only refs are kept for telemetry. They carry no value and the contract never reads them.
    discovery_refs: tuple[str, ...] = field(default=(), compare=False)


_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTH_NAMES) + r")\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d\d\b")


def _period_matches(period: tuple[str, str], sentence: str) -> bool:
    """Whether a past record's OWN sentence is dated in a way that satisfies the month the question names. "in M": the sentence names M. "as of M": the same. "before M": the sentence names at least one month and
    every month it names is earlier in the calendar than M. No year is ever compared (the records carry none here); a sentence that names a year, or no month, never matches."""
    kind, month = period
    named = [_MONTH_NAMES.index(m.lower()) for m in _MONTH_RE.findall(sentence)]
    if not named or _YEAR_RE.search(sentence) or month not in _MONTH_NAMES:
        return False
    asked = _MONTH_NAMES.index(month)
    if kind == "before":
        return all(n < asked for n in named)
    return asked in named


def _group(facts: Collection[AdmittedFact]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    by: dict[str, list[str]] = {}
    display: dict[str, str] = {}
    for f in facts:
        key = f.value.casefold()
        display.setdefault(key, f.value)
        by.setdefault(key, [])
        if f.ref not in by[key]:
            by[key].append(f.ref)
    return tuple((display[k], tuple(refs)) for k, refs in by.items())


def _drop_superseded(facts: list[AdmittedFact], supersessions: Collection[tuple[str, str]]) -> tuple[list[AdmittedFact], bool]:
    older = {old for new, old in supersessions if any(f.ref == new for f in facts)}
    kept = [f for f in facts if f.ref not in older]
    return kept, len(kept) != len(facts)


_REL_TIME = re.compile(r"\b(?:this|next|last|current|previous)\s+(?:week|month|quarter|year|sprint|weekend)\b|\b(?:today|tonight|tomorrow|yesterday)\b", re.IGNORECASE)


def _group_status(facts: Collection[AdmittedFact]) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    out: dict[tuple[str, str], list[str]] = {}
    shown: dict[tuple[str, str], str] = {}
    for f in facts:
        key = (f.value.casefold(), f.status)
        shown.setdefault(key, f.value)
        refs = out.setdefault(key, [])
        if f.ref not in refs:
            refs.append(f.ref)
    return tuple((shown[k], k[1], tuple(refs)) for k, refs in out.items())


def _decide_core(component: Component, result: AdmissionResult, supersessions: Collection[tuple[str, str]] = (), *, many: bool = False) -> Ticket:
    """Only a value the record says is CONFIGURED or DEPLOYED can be the current value. Decided and planned values are reported as such (`pending`), retired and rolled-back values never answer (`out_of_use`); a value
    that one record states as live and another states as retired is not chosen either way (nothing here resolves a disagreement between records)."""
    every = list(result.facts)
    live = [f for f in every if f.status in transitions.LIVE]
    t = _decide_live(component, replace(result, facts=tuple(live)), supersessions, many=many)
    if component.ask is not Ask.VALUE or component.relation is None:
        return t
    # a decided or planned value is reported only when nothing says it is already in place: not when it is the answer, and not when ANY current (non-past) record states it as configured or deployed. A question
    # about the past gets no such note at all (a decision is not what was in place then).
    in_place = {v.casefold() for v, _ in t.values} | {f.value.casefold() for f in live if f.scope is not FactScope.PAST}
    pending = () if component.scope is Scope.PAST else tuple(p for p in _group_status([f for f in every if f.status in transitions.PENDING]) if p[0].casefold() not in in_place)
    out = _group([f for f in every if f.status in transitions.OUT_OF_USE])
    t = replace(t, pending=pending, out_of_use=out)
    retired_values = {v.casefold(): set(refs) for v, refs in out}
    if retired_values and t.state is State.SUPPORTED:  # a CONFLICTED ticket already chooses nothing and is kept as it is
        clash = [f for f in live if f.scope is not FactScope.PAST and f.value.casefold() in retired_values and f.ref not in retired_values[f.value.casefold()]]
        if clash:  # live in one record, retired in another: the records disagree about that value and nothing says which holds
            return Ticket(component, _empty_state(component), (AMBIGUITY, "value_stated_retired_in_another_record"), ambiguous_refs=t.ambiguous_refs, out_of_use=out, discovery_refs=t.discovery_refs)
    if t.state in (State.SUPPORTED, State.HISTORICAL) and t.values:
        supporting = [f for f in live if f.ref in {r for _, refs in t.values for r in refs}]
        phrases = [{m.casefold() for m in _REL_TIME.findall(f.sentence)} for f in supporting]
        if any(phrases):
            if all(len(p) == 1 for p in phrases) and len({next(iter(p)) for p in phrases}) == 1:
                t = replace(t, time_phrase=next(iter(phrases[0])))
            else:  # a relative time ("this month") in some supporting records and not in others, or different ones: the claim cannot be stated plainly
                return Ticket(component, _empty_state(component), (AMBIGUITY, "relative_time_differs_between_records"), ambiguous_refs=t.ambiguous_refs, out_of_use=out, discovery_refs=t.discovery_refs)
    return t


def _decide_live(component: Component, result: AdmissionResult, supersessions: Collection[tuple[str, str]] = (), *, many: bool = False) -> Ticket:
    facts = list(result.facts)
    amb = tuple(ref for ref, _ in result.ambiguous)
    base = {"ambiguous_refs": amb, "discovery_refs": result.discovery_only}
    note = ("ambiguous_record_on_same_subject",) if amb else ()
    if component.relation is None:
        return Ticket(component, _empty_state(component), ("no_relation_spec", "clause_not_understood", *note), **base)

    if component.ask is Ask.ORDERING:
        values = _group(facts)
        authoritative = [f for f in facts if f.provenance.author_class in AUTHORITATIVE]
        starts = {f.ref: f.provenance.effective_start for f in authoritative if f.provenance.effective_start is not None}
        pairs = [(new, old) for new, old in supersessions if any(f.ref == new for f in facts) and any(f.ref == old for f in facts)]
        if pairs:
            return Ticket(component, State.SUPPORTED, ("explicit_supersession", *note), values, ordering_basis="explicit_supersession", **base)
        if len({v for v, _ in values}) >= 2 and len(set(starts.values())) >= 2 and set(starts) >= {r for _, refs in values for r in refs}:
            return Ticket(component, State.SUPPORTED, ("explicit_effective_periods", *note), values, ordering_basis="explicit_effective_start", **base)
        return Ticket(component, State.ORDER_UNSUPPORTED, ("no_explicit_ordering_basis", *note), values, **base)

    if component.ask is Ask.EXISTENCE:
        neg = [f for f in facts if f.polarity == "negates"]
        pres = [f for f in facts if f.polarity == "asserts"]
        # an ended or archived statement is not a statement about now
        if component.scope is Scope.CURRENT:
            neg = [f for f in neg if f.scope is not FactScope.PAST]
            pres = [f for f in pres if f.scope is not FactScope.PAST]
        if neg and pres:
            return Ticket(component, State.CONFLICTED, ("presence_and_absence_both_recorded", *note), (("absent", tuple(dict.fromkeys(f.ref for f in neg))), ("present", tuple(dict.fromkeys(f.ref for f in pres)))), **base)
        authoritative_neg = [f for f in neg if f.provenance.author_class in AUTHORITATIVE]
        if authoritative_neg:  # rubric v5 class 2: only an authoritative record establishes absence; scoped searches add nothing to it
            return Ticket(component, State.NEGATIVE_SUPPORTED, ("record_states_absence", *note), (("absent", tuple(dict.fromkeys(f.ref for f in authoritative_neg))),), **base)
        if pres:  # a presence record decides; a search of one place that found nothing is consistent with it existing elsewhere
            return Ticket(component, State.SUPPORTED, ("record_states_presence", *note), (("present", tuple(dict.fromkeys(f.ref for f in pres))),), **base)
        if neg:  # "there is no X" from a non-authoritative author: attributed, not established (rubric v5 class 2 needs an authoritative record)
            return Ticket(component, State.NEGATIVE_UNSUPPORTED, ("absence_not_authoritative", *note), (("absent", tuple(dict.fromkeys(f.ref for f in neg))),),
                          absence_authors=tuple(dict.fromkeys(f.provenance.author_class.value for f in neg)), scoped=result.scoped, **base)
        if result.scoped:  # rubric v5 class 1: a verifiable bounded search; reported with its scope, never as absence
            return Ticket(component, State.NEGATIVE_UNSUPPORTED, ("scoped_search_negative", *note), scoped=result.scoped, **base)
        return Ticket(component, State.NEGATIVE_UNSUPPORTED, ("no_record_asserts_presence_or_absence", *note), **base)

    # VALUE
    in_scope_past = [f for f in facts if f.scope is FactScope.PAST]
    live = [f for f in facts if f.scope is not FactScope.PAST]
    live, was_superseded = _drop_superseded(live, supersessions)
    past, _ = _drop_superseded(in_scope_past, supersessions)
    if component.scope is Scope.PAST:
        if component.period is not None:
            matching = [f for f in past if _period_matches(component.period, f.sentence)]
            if past and not matching:  # the question names a month and no past record's own sentence is dated to it: nothing is said about that period
                return Ticket(component, State.UNSUPPORTED, ("no_record_for_requested_period", *note), **base)
            past = matching
        if past:
            return Ticket(component, State.HISTORICAL, ("explicit_past_record", *note), _group(past), **base)
        return Ticket(component, State.UNSUPPORTED, ("no_record_marked_past", *note), **base)
    history = _group(past)
    if not live:
        if past:
            return Ticket(component, State.HISTORICAL, ("only_past_records_for_a_current_question", *note), _group(past), **base)
        return Ticket(component, State.UNSUPPORTED, ("no_admitted_record", *note), **base)
    values = _group(live)
    if len(values) > 1 and not many:
        return Ticket(component, State.CONFLICTED, ("admitted_records_disagree", "no_explicit_supersession", *note), values, history, **base)
    reasons = ("single_value", *(("older_record_explicitly_superseded",) if was_superseded else ()), *note)
    return Ticket(component, State.SUPPORTED, reasons, values, history, **base)


AMBIGUITY = "ambiguity_on_requested_proposition"


def _ambiguity_touches(component: Component, result: AdmissionResult) -> bool:
    """An ambiguous sentence about this subject and relation that could bear on the time the question asks about."""
    for scope in result.ambiguous_scopes:
        if component.scope is Scope.ANY or (component.scope is Scope.PAST and scope is not FactScope.CURRENT) or (component.scope is Scope.CURRENT and scope is not FactScope.PAST):
            return True
    return False


def decide(component: Component, result: AdmissionResult, supersessions: Collection[tuple[str, str]] = (), *, many: bool = False) -> Ticket:
    """Ambiguity applies at the smallest affected proposition. A sentence that is about THIS subject and relation but cannot be read safely (hedged, negated, several values, competing subject, unreadable
    text value) makes a single-valued answer unchoosable: the ticket is withheld, never resolved in favour of a clean-looking record. For a many-valued relation each value is its own proposition, so the
    independent supported values stay answered (the contract adds a caveat); a CONFLICTED ticket chooses nothing and is kept. Other components are never touched."""
    t = _decide_core(component, result, supersessions, many=many)
    if component.relation is None or not _ambiguity_touches(component, result):
        return t
    if many and component.ask is Ask.VALUE:
        return t
    if t.state in (State.SUPPORTED, State.HISTORICAL, State.NEGATIVE_SUPPORTED) or (t.state is State.SUPPORTED and component.ask is Ask.ORDERING):
        return Ticket(component, _empty_state(component), (AMBIGUITY, *t.reasons[:0]), ambiguous_refs=t.ambiguous_refs, discovery_refs=t.discovery_refs)
    if t.state in (State.CONFLICTED, State.UNSUPPORTED, State.NEGATIVE_UNSUPPORTED, State.ORDER_UNSUPPORTED):
        return replace(t, reasons=(*t.reasons, AMBIGUITY))  # nothing was chosen; the reply says the records are unclear rather than that they are silent
    return t


def _empty_state(component: Component) -> State:
    return {Ask.EXISTENCE: State.NEGATIVE_UNSUPPORTED, Ask.ORDERING: State.ORDER_UNSUPPORTED}.get(component.ask, State.UNSUPPORTED)
