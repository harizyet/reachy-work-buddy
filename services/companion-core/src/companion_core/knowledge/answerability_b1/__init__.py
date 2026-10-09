"""Phase 44 selective answering, Stage B-1: the deterministic answerability pipeline (owner-approved 2026-10-13; DESIGN: docs/phase-44-selective-stage-b-design.md).

discovery evidence -> admissible evidence -> per-claim answerability state -> response contract. Pure functions over data; **no model call, no I/O, not imported by any reply path, no migration.** It is source
code only, like knowledge/sufficiency.py: nothing in production references it. Retrieval and shadow stay off.

Invariants (each has a test): discovery items are a different type from admitted facts and nothing promotes one into the other except `admission.admit`; retrieval time and record creation time never
establish recency or supersession; supersession needs an explicit authoritative statement or explicit effective periods from authoritative authors; absence is never asserted without a record that says so;
ambiguous or unparsable evidence is never admitted and never produces an assertion; every cited evidence id maps to a record that supports the claim it is attached to."""

from companion_core.knowledge.answerability_b1.admission import (
    AdmissionPolicy,
    AdmissionResult,
    admit,
    find_supersessions,
)
from companion_core.knowledge.answerability_b1.contract import (
    Claim,
    Plan,
    build_plan,
    decompose,
    render_claim,
)
from companion_core.knowledge.answerability_b1.states import Ticket, decide
from companion_core.knowledge.answerability_b1.types import (
    AdmittedFact,
    Ask,
    AuthDecision,
    AuthorClass,
    Component,
    DiscoveryItem,
    FactScope,
    Provenance,
    RelationSpec,
    Scope,
    State,
)

__all__ = ["AdmissionPolicy", "AdmissionResult", "AdmittedFact", "Ask", "AuthDecision", "AuthorClass", "Claim", "Component", "DiscoveryItem", "FactScope", "Plan", "Provenance", "RelationSpec", "Scope", "State",
           "Ticket", "admit", "build_plan", "decide", "decompose", "find_supersessions", "render_claim"]
