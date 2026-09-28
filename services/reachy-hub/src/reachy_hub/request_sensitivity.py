"""Pre-Core request sensitivity and authorization (Phase 25.0, ADR 0024).

`AgentResponse.privacy` (shared/models/response.py) already classifies
*output*. This module adds the *input* side: given a trust level already
computed by `reachy_hub.trust.effective_trust`, and a request's sensitivity,
decide whether the transcript may even reach Companion Core. The LLM may
suggest a sensitivity classification where useful, but only this
deterministic function decides trust sufficiency, and it never lowers the
required trust level for an ambiguous request (docs/phase-25.md).

`InteractionMode.TRUSTED` (ADR 0006 addendum) changes response routing, not
identity or action authorization: it has no effect on the decision here,
deliberately.
"""

from __future__ import annotations

from enum import StrEnum

from shared.models.session import InteractionMode
from shared.models.trust import TrustLevel, trust_at_least


class RequestSensitivity(StrEnum):
    PUBLIC = "public"
    PERSONAL = "personal"
    CONSEQUENTIAL = "consequential"
    UNKNOWN = "unknown"


class InteractionDecision(StrEnum):
    ALLOW = "allow"
    WITHHOLD = "withhold"
    PRIVATE_ROUTE = "private_route"
    REQUIRE_VERIFICATION = "require_verification"
    DENY = "deny"


def authorize_request(
    sensitivity: RequestSensitivity,
    trust: TrustLevel,
    interaction_mode: InteractionMode,
) -> InteractionDecision:
    """(sensitivity, trust, interaction_mode) -> decision, deterministically.

    `interaction_mode` is accepted for forward compatibility with later
    routing-aware gates but does not change the outcome today — Trusted mode
    in particular must not bypass this policy (docs/phase-25.md).
    """
    del interaction_mode

    if sensitivity == RequestSensitivity.PUBLIC:
        return InteractionDecision.ALLOW

    # UNKNOWN always fails upward, toward more verification, never less: an
    # ambiguous classification never resolves to ALLOW on trust alone, even
    # at T2/T3, because the request itself hasn't been confidently sized yet.
    if sensitivity == RequestSensitivity.UNKNOWN:
        return InteractionDecision.REQUIRE_VERIFICATION

    # PERSONAL and CONSEQUENTIAL both require at least T2 (fresh voice plus
    # fresh visual owner evidence) before the transcript may reach Core.
    # Core's own action policy (ADR 0011) still gates CONSEQUENTIAL further.
    if trust_at_least(trust, TrustLevel.T2):
        return InteractionDecision.ALLOW

    return InteractionDecision.REQUIRE_VERIFICATION
