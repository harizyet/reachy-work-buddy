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

import re
from enum import StrEnum

from shared.models.session import InteractionMode
from shared.models.trust import TrustLevel, trust_at_least


class RequestSensitivity(StrEnum):
    PUBLIC = "public"
    PERSONAL = "personal"
    CONSEQUENTIAL = "consequential"
    UNKNOWN = "unknown"


# Deterministic, high-confidence rules only (docs/phase-25.md's
# classification flow: rules -> obvious? yes: use it; no: UNKNOWN, fail
# upward). No LLM-assist layer exists yet, so this stage is deliberately
# conservative: an ordinary open-ended question that isn't one of these
# recognized public phrasings comes out UNKNOWN, not PUBLIC. That is safe
# by design (UNKNOWN requires the same trust as CONSEQUENTIAL) but means
# most everyday questions won't be answered at T0/T1 once the sensitivity
# gate is enabled, until a classifier/LLM-suggestion stage is added.
_CONSEQUENTIAL_RE = re.compile(
    r"\b(send|delete|remove|cancel|book|schedule|create|forward|reply to|share)\b.*"
    r"\b(email|mail|message|event|meeting|appointment|calendar|reminder|task)\b"
)
_PERSONAL_RE = re.compile(
    r"\bmy\s+(email|mail|inbox|calendar|appointment|schedule|note|notes|reminder|reminders|task|tasks)\b"
    r"|\b(read|check|show|what'?s in)\s+my\b"
    r"|\bnext\s+appointment\b"
)
_PUBLIC_RE = re.compile(
    r"\bwhat\s+time\s+is\s+it\b|\bwhat\s+day\s+is\s+it\b"
    r"|\bwhat'?s\s+the\s+weather\b|\bweather\s+(?:like\s+)?(?:today|tomorrow|outside)\b"
    r"|\btell\s+me\s+a\s+joke\b"
)


def classify_sensitivity(transcript: str) -> RequestSensitivity:
    """Deterministic rules only; ambiguous input fails upward to UNKNOWN,
    never down to PUBLIC. Checked in order of consequence: a transcript
    matching both a consequential and a public-sounding phrase (unlikely,
    but a crafted "what time is it, then delete my calendar" must not
    slip through as public) is CONSEQUENTIAL."""
    normalized = transcript.strip().lower()
    if not normalized:
        return RequestSensitivity.UNKNOWN
    if _CONSEQUENTIAL_RE.search(normalized):
        return RequestSensitivity.CONSEQUENTIAL
    if _PERSONAL_RE.search(normalized):
        return RequestSensitivity.PERSONAL
    if _PUBLIC_RE.search(normalized):
        return RequestSensitivity.PUBLIC
    return RequestSensitivity.UNKNOWN


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
