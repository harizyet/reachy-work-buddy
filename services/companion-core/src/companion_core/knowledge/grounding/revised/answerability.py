"""REVISED C2: a calibrated ANNOTATION, never a gate. Same states and the same computation as the frozen module (it is imported, not copied); what changes is the contract:
- the note is hedged ("may be wrong") because C2 is a lexical judgement with measured error rates;
- `calibration()` turns labelled examples into per-state precision and recall, so any use can quote the measured reliability;
- there is NO deterministic reply: a state never replaces the generator's answer, and the template reply of the frozen module is deliberately not re-exported (owner decision: rejected)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from companion_core.knowledge.grounding.answerability import (
    CONFLICTED,
    ESTABLISHED,
    PARTIAL,
    UNESTABLISHED,
    Answerability,
    Clause,
    assess,
)

__all__ = ["CONFLICTED", "ESTABLISHED", "PARTIAL", "UNESTABLISHED", "Answerability", "Clause", "assess", "calibration", "note"]


def note(a: Answerability) -> str | None:
    if a.state == ESTABLISHED:
        return None
    if a.state == UNESTABLISHED:
        who = ", ".join(a.clauses[0].subjects) if a.clauses and a.clauses[0].subjects else "this"
        return f"Automatic check (a lexical estimate that may be wrong): no record below appears to state what was asked about {who}."
    if a.state == CONFLICTED:
        return "Automatic check (an estimate that may be wrong): records below appear to give different values for the same fact; report each with its source."
    missing = [", ".join(c.subjects) or "a part" for c in a.clauses if c.state == UNESTABLISHED]
    return f"Automatic check (an estimate that may be wrong): one part of the question may not be stated in any record below ({'; '.join(missing)})."


def calibration(pairs: Sequence[tuple[str, str]]) -> dict:
    """`pairs`: (gold label, predicted state), labels collapsed to ESTABLISHED / CONFLICTED / PARTIAL / UNESTABLISHED. Returns per predicted state: how many, precision; per gold label: recall."""
    pred = Counter(p for _, p in pairs)
    gold = Counter(g for g, _ in pairs)
    hit = Counter(g for g, p in pairs if g == p)
    return {"n": len(pairs), "precision": {s: round(hit[s] / pred[s], 3) for s in pred}, "recall": {s: round(hit[s] / gold[s], 3) for s in gold}, "predicted": dict(pred), "gold": dict(gold)}
