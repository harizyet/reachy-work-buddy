"""C2: an explicit answerability state, computed from C1's selection (the question's proposition against the authorised evidence) and from nothing the generator says.

  ESTABLISHED   every clause of the question has an asserting sentence window with a value
  CONFLICTED    some clause has asserting windows in different records that give different values
  PARTIAL       some clauses are established and some are not
  UNESTABLISHED no clause is established. `reason`: related_other_subject (the relation is asserted, but about other things), subject_other_relation (the subject appears, the relation does not), nothing

The state never depends on a model, so it can be evaluated with a null generator. It may be used to add a factual note, to suppress an answer a generator proposes while the state is UNESTABLISHED, or to
render a deterministic reply; it can never be raised by what a generator says. A reply built from it names only authorised material and is identical whether the missing fact is absent or unauthorised."""

from __future__ import annotations

from dataclasses import dataclass, field

from companion_core.knowledge.grounding.propositions import Selection

ESTABLISHED, PARTIAL, CONFLICTED, UNESTABLISHED = "ESTABLISHED", "PARTIAL", "CONFLICTED", "UNESTABLISHED"


@dataclass
class Clause:
    state: str
    values: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    relation: str | None = None


@dataclass
class Answerability:
    state: str
    clauses: list[Clause] = field(default_factory=list)
    reason: str | None = None


def _norm(v: str) -> str:
    return v.lower().strip()


def assess(sel: Selection, *, strict_qualifiers: bool = False) -> Answerability:
    clauses: list[Clause] = []
    for ci, prop in enumerate(sel.propositions):
        if prop.structured:  # answered by C3 from an authoritative store; not judged from text here
            clauses.append(Clause(ESTABLISHED, (), prop.subjects, prop.relation))
            continue
        # a question about the present ignores statements marked as past; a question about the past uses only those
        found = [a for a in sel.assertions[ci] if a.historical == sel.history] or ([] if not sel.history else [a for a in sel.assertions[ci]])
        if strict_qualifiers and sel.absent_qualifiers[ci] and not found:
            clauses.append(Clause(UNESTABLISHED, (), prop.subjects, prop.relation))
            continue
        by_item: dict[int, set[str]] = {}
        for a in found:
            by_item.setdefault(a.item_index, set()).update(_norm(v) for v in a.values)
        if not found:
            clauses.append(Clause(UNESTABLISHED, (), prop.subjects, prop.relation))
            continue
        distinct = set().union(*by_item.values())
        # a conflict needs two different records that share no value; windows that merely mention extra names in one record are not conflicts
        records = list(by_item.values())
        conflict = len(records) >= 2 and any(not (records[i] & records[j]) for i in range(len(records)) for j in range(i + 1, len(records)))
        clauses.append(Clause(CONFLICTED if conflict else ESTABLISHED, tuple(sorted(distinct)), prop.subjects, prop.relation))
    states = {c.state for c in clauses}
    if CONFLICTED in states:
        state = CONFLICTED
    elif states == {ESTABLISHED}:
        state = ESTABLISHED
    elif ESTABLISHED in states:
        state = PARTIAL
    else:
        state = UNESTABLISHED
    reason = None
    if state == UNESTABLISHED:
        reason = "related_other_subject" if any(sel.other_subject_assertions) else ("subject_other_relation" if sel.related else "nothing")
    return Answerability(state, clauses, reason)


def note(a: Answerability) -> str | None:
    """A factual line for the evidence message, written by code. No model text, no values from unauthorised records (the selection only ever contains authorised ones)."""
    if a.state == ESTABLISHED:
        return None
    if a.state == UNESTABLISHED:
        who = ", ".join(a.clauses[0].subjects) if a.clauses and a.clauses[0].subjects else "this"
        return f"Automatic check: no record below states what was asked about {who}."
    if a.state == CONFLICTED:
        return "Automatic check: records below give different values for the same fact; report both."
    missing = [", ".join(c.subjects) or "a part" for c in a.clauses if c.state == UNESTABLISHED]
    return f"Automatic check: one part of the question is not stated in any record below ({'; '.join(missing)})."


def template_reply(a: Answerability) -> str | None:
    """Deterministic reply for UNESTABLISHED only. It does not say whether related records exist elsewhere, so it cannot reveal anything the owner may not see."""
    if a.state != UNESTABLISHED:
        return None
    who = ", ".join(a.clauses[0].subjects) if a.clauses and a.clauses[0].subjects else "that"
    return f"I don't have a record that says that for {who}."
