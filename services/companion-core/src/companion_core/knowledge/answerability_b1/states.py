"""Per-claim answerability: a pure function from the admitted facts for ONE component to one of seven states. One component's ticket never depends on another's.

Rules (Stage B design section 3). Time: only a record's explicit wording or explicit effective period says when a fact holds. Retrieval time and record creation time are not inputs here (they are not even
on the admitted fact's decision path), so neither can establish recency or supersession.

  VALUE   facts in scope  -> one value SUPPORTED | several values CONFLICTED (unless an explicit authoritative supersession removes the older) | only past facts for a current question, or a past
          question answered by past facts -> HISTORICAL | nothing in scope -> UNSUPPORTED
  EXISTENCE  negating fact only -> NEGATIVE_SUPPORTED | asserting fact only -> SUPPORTED | both -> CONFLICTED | neither -> NEGATIVE_UNSUPPORTED (never "does not exist")
  ORDERING   explicit authoritative supersession, or two authoritative facts with explicit and different effective starts -> SUPPORTED with the stated basis | otherwise ORDER_UNSUPPORTED, keeping the values
Ambiguous, unreadable or unauthorised records contribute nothing; an ambiguous record that touches the same subject and relation is reported on the ticket so the reply can say so."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

from companion_core.knowledge.answerability_b1.admission import AdmissionResult
from companion_core.knowledge.answerability_b1.types import (
    AUTHORITATIVE,
    AdmittedFact,
    Ask,
    Component,
    FactScope,
    Scope,
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
    # discovery-only refs are kept for telemetry. They carry no value and the contract never reads them.
    discovery_refs: tuple[str, ...] = field(default=(), compare=False)


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


def decide(component: Component, result: AdmissionResult, supersessions: Collection[tuple[str, str]] = (), *, many: bool = False) -> Ticket:
    facts = list(result.facts)
    amb = tuple(ref for ref, _ in result.ambiguous)
    base = {"ambiguous_refs": amb, "discovery_refs": result.discovery_only}
    note = ("ambiguous_record_on_same_subject",) if amb else ()
    if component.relation is None:
        return Ticket(component, _empty_state(component), ("no_relation_spec", *note), **base)

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
        if neg:
            return Ticket(component, State.NEGATIVE_SUPPORTED, ("record_states_absence", *note), (("absent", tuple(dict.fromkeys(f.ref for f in neg))),), **base)
        if pres:
            return Ticket(component, State.SUPPORTED, ("record_states_presence", *note), (("present", tuple(dict.fromkeys(f.ref for f in pres))),), **base)
        return Ticket(component, State.NEGATIVE_UNSUPPORTED, ("no_record_asserts_presence_or_absence", *note), **base)

    # VALUE
    in_scope_past = [f for f in facts if f.scope is FactScope.PAST]
    live = [f for f in facts if f.scope is not FactScope.PAST]
    live, was_superseded = _drop_superseded(live, supersessions)
    past, _ = _drop_superseded(in_scope_past, supersessions)
    if component.scope is Scope.PAST:
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


def _empty_state(component: Component) -> State:
    return {Ask.EXISTENCE: State.NEGATIVE_UNSUPPORTED, Ask.ORDERING: State.ORDER_UNSUPPORTED}.get(component.ask, State.UNSUPPORTED)
