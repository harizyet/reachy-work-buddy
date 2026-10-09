"""Groundedness components (Phase 44 milestone; EXPERIMENTAL, local development on an invented corpus; nothing here is wired into any answer path).

C1 `propositions`: proposition- and relationship-aware evidence selection.  C2 `answerability`: an explicit ESTABLISHED / PARTIAL / CONFLICTED / UNESTABLISHED state computed from C1's output and never
from the generator.  C3 `routes`: authoritative structured-store routing where a relation maps cleanly.  C4 `claims`: atomic-claim generation schema and rendering.  C5 `validate`: independent
validation of every atomic claim's source identity, authorization, exact evidence span and supported relation. Each is separable and has its own tests."""
