"""The response contract: what a later generator may assert, what code writes, and which evidence id supports which claim.

For every component the contract holds the state, the code-written sentence for every state that is not a plain model-written value (withheld, conflict, absence, ordering), and a CLAIM-LEVEL citation mapping:
each assertable value lists the evidence ids of exactly the admitted records that state that value. A shared id is never inferred. A supporting record with no evidence id in this turn makes the component
uncitable and it is withheld ("fail closed on assertion"). Discovery-only and ambiguous records have no path into the contract's values or citations; ambiguity is reported as a code-written caveat.
Nothing here calls a model. `render_claim` is also a complete deterministic rendering (the no-model "typed" arm of the design); a later stage may let a model phrase SUPPORTED/HISTORICAL values only."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from companion_core.knowledge.answerability_b1.admission import (
    AdmissionPolicy,
    admit,
    find_supersessions,
)
from companion_core.knowledge.answerability_b1.states import (
    Ticket,
    _empty_state,
    decide,
)
from companion_core.knowledge.answerability_b1.types import (
    Ask,
    AuthDecision,
    Component,
    DiscoveryItem,
    RelationSpec,
    Scope,
    State,
)

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_ORDERING_Q = re.compile(r"\b(?:updated|newer|older|replaced|superseded|changed|which (?:one )?(?:came )?first|latest|most recent|overrid\w+)\b", re.IGNORECASE)
_EXISTENCE_Q = re.compile(r"\b(?:is there|are there|does \w+(?: \w+)? have|do \w+(?: \w+)? have|has \w+(?: \w+)? (?:a|an)\b|any)\b", re.IGNORECASE)
_PAST_Q = re.compile(rf"\b(?:old|previous|previously|formerly|used to|before|earlier|archived|originally|in (?:{_MONTHS}))\b", re.IGNORECASE)
_CURRENT_Q = re.compile(r"\b(?:now|currently|current|at present|today)\b", re.IGNORECASE)
_CLAUSE = re.compile(r"\?|,? and (?=\w)|,\s*(?=\w)|;", re.IGNORECASE)


@dataclass(frozen=True)
class Claim:
    component_id: str
    state: State
    text: str  # code-written; contains only fixed words, the component label, admitted values and evidence ids
    assertable: tuple[tuple[str, tuple[str, ...]], ...]  # (value, evidence ids) the claim may assert
    model_may_phrase: bool  # True only for SUPPORTED / HISTORICAL value claims
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    claims: tuple[Claim, ...]
    tickets: tuple[Ticket, ...]
    fallback: bool  # True: the question could not be decomposed and typed; the caller keeps the existing path for this turn (never a refusal)
    errors: tuple[tuple[str, str], ...] = ()
    text: str = field(default="")  # the deterministic rendering of every claim in question order

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.claims:
            out[c.state.value] = out.get(c.state.value, 0) + 1
        return out


def _label(component: Component, spec: RelationSpec | None) -> str:
    if component.label:
        return component.label
    if spec is None:
        return component.subject
    return f"{spec.words} {spec.joiner} {component.subject}"


def _cite(eids: tuple[str, ...]) -> str:
    return " ".join(f"[{e}]" for e in eids)


def render_claim(ticket: Ticket, label: str, eid_for: Mapping[str, str]) -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]:
    """(text, claim-level citations) for one ticket. Raises KeyError when a supporting record has no evidence id (the caller then withholds the component)."""
    cites = tuple((v, tuple(dict.fromkeys(eid_for[r] for r in refs))) for v, refs in ticket.values)
    tuple((v, tuple(dict.fromkeys(eid_for[r] for r in refs))) for v, refs in ticket.history)
    caveat = " Another record on this could not be read reliably, so it is not used." if ticket.ambiguous_refs else ""
    s = ticket.state
    if "ambiguity_on_requested_proposition" in ticket.reasons and not ticket.values:
        return f"The records on the {label} are unclear, so I will not pick an answer.", ()
    if s is State.SUPPORTED and ticket.component.ask is Ask.EXISTENCE:
        return f"The records say there is a {label} {_cite(cites[0][1])}.{caveat}", cites
    if s is State.SUPPORTED and ticket.component.ask is Ask.ORDERING:
        basis = {"explicit_supersession": "a record explicitly says it replaces the other", "explicit_effective_start": "the records state different effective start dates"}[ticket.ordering_basis]
        return f"For the {label}: {', '.join(f'{v} {_cite(e)}' for v, e in cites)}; {basis}.{caveat}", cites
    if s is State.SUPPORTED:
        return f"The {label} is {' and '.join(f'{v} {_cite(e)}' for v, e in cites)}.{caveat}", cites
    if s is State.HISTORICAL:
        now_note = " The records do not say what it is now." if ticket.component.scope is not Scope.PAST else ""
        return f"Previously, the {label} was {' and '.join(f'{v} {_cite(e)}' for v, e in cites)}.{now_note}{caveat}", cites
    if s is State.CONFLICTED:
        if ticket.component.ask is Ask.EXISTENCE:
            return f"The records disagree on whether there is a {label}: one says there is {_cite(cites[1][1])}, another says there is not {_cite(cites[0][1])}. They do not say which applies.{caveat}", cites
        parts = "; ".join(f"one record says {v} {_cite(e)}" for v, e in cites)
        return f"The records disagree on the {label}: {parts}. They do not say which applies.{caveat}", cites
    if s is State.NEGATIVE_SUPPORTED:
        return f"The records say there is no {label} {_cite(cites[0][1])}.{caveat}", cites
    if s is State.NEGATIVE_UNSUPPORTED:
        return f"The records I searched do not mention a {label}.{caveat}", ()
    if s is State.ORDER_UNSUPPORTED:
        if len(cites) >= 2:
            return f"The records give {' and '.join(f'{v} {_cite(e)}' for v, e in cites)} for the {label}, but nothing in them dates one before the other.{caveat}", cites
        return f"Nothing in the records establishes an order for the {label}.{caveat}", ()
    return f"The records do not say the {label}.{caveat}", ()  # UNSUPPORTED


def _claim(ticket: Ticket, spec: RelationSpec | None, eid_for: Mapping[str, str]) -> Claim:
    label = _label(ticket.component, spec)
    try:
        text, cites = render_claim(ticket, label, eid_for)
    except KeyError:
        down = Ticket(ticket.component, _empty_state(ticket.component), ("supporting_record_not_citable",), ambiguous_refs=ticket.ambiguous_refs, discovery_refs=ticket.discovery_refs)
        text, cites = render_claim(down, label, eid_for)
        return Claim(ticket.component.id, down.state, text, (), False, down.reasons)
    return Claim(ticket.component.id, ticket.state, text, cites, ticket.state in (State.SUPPORTED, State.HISTORICAL) and ticket.component.ask is Ask.VALUE, ticket.reasons)


def build_plan(components: Collection[Component], items: Collection[DiscoveryItem], auths: Mapping[str, AuthDecision], *, now: datetime, specs: Mapping[str, RelationSpec],
               eids: Mapping[str, str], known_subjects: Collection[str], policy: AdmissionPolicy, fallback: bool = False, structured: Collection = ()) -> Plan:
    supersessions = find_supersessions(items, auths, now=now, policy=policy)
    tickets: list[Ticket] = []
    claims: list[Claim] = []
    errors: list[tuple[str, str]] = []
    for comp in components:
        spec = specs.get(comp.relation) if comp.relation else None
        try:
            if comp.relation is not None and spec is None:
                raise LookupError("no relation spec")
            result = admit(comp, items, auths, now=now, spec=spec, known_subjects=known_subjects, policy=policy, structured=structured)
            ticket = decide(comp, result, supersessions, many=bool(spec and spec.many))
            claim = _claim(ticket, spec, eids)
        except Exception as exc:  # one component failing never takes the others down; it is withheld with distinct wording  # noqa: BLE001
            errors.append((comp.id, type(exc).__name__))
            ticket = Ticket(comp, _empty_state(comp), ("check_failed",))
            claim = Claim(comp.id, ticket.state, f"I could not check the {_label(comp, spec)}.", (), False, ("check_failed",))
        tickets.append(ticket)
        claims.append(claim)
    return Plan(tuple(claims), tuple(tickets), fallback, tuple(errors), " ".join(c.text for c in claims))


def decompose(question: str, specs: Mapping[str, RelationSpec], subjects: Mapping[str, tuple[str, ...]]) -> tuple[tuple[Component, ...], bool]:
    """Deterministic split into components. Returns (components, fallback). Any clause whose subject or relation cannot be determined unambiguously makes `fallback` True (the existing path then keeps
    the turn); typed clauses are still returned for telemetry. `subjects` maps a canonical subject to its aliases."""
    parts = [p.strip() for p in _CLAUSE.split(question) if p and p.strip()]
    comps: list[Component] = []
    fallback = not parts
    for n, clause in enumerate(parts, 1):
        subj = [canon for canon, aliases in subjects.items() if any(re.search(rf"\b{re.escape(a)}\b", clause, re.IGNORECASE) for a in aliases)]
        rels = [name for name, sp in specs.items() if any(re.search(c, clause, re.IGNORECASE) for c in sp.cues)]
        if len(subj) != 1 or len(rels) != 1:
            fallback = True
            comps.append(Component(f"c{n}", subj[0] if len(subj) == 1 else clause, tuple(subjects.get(subj[0], ())) if len(subj) == 1 else (), None))
            continue
        spec = specs[rels[0]]
        ask = Ask.ORDERING if _ORDERING_Q.search(clause) else Ask.EXISTENCE if spec.kind == "existence" and _EXISTENCE_Q.search(clause) else Ask.VALUE
        scope = Scope.PAST if _PAST_Q.search(clause) else Scope.CURRENT if _CURRENT_Q.search(clause) else Scope.ANY
        comps.append(Component(f"c{n}", subj[0], tuple(subjects[subj[0]]), spec.name, ask, scope))
    return tuple(comps), fallback
