"""Owner-recognition identity evidence and progressive trust (Phase 25,
ADR 0024). Shared by reachy-hub (trust computation, request authorization)
and any service that needs to reason about a trust level without importing
reachy-hub directly.

Evidence, trust and authorization are three distinct concepts (docs/phase-25.md
"Trust, evidence and authorization are three distinct concepts"): a
recognition score becomes one field of the evidence below, the evidence
becomes a `TrustLevel`, and only then does a request authorizer weigh that
level against `RequestSensitivity`. Nothing here decides whether a request is
allowed. Evidence is transient process state (see
`reachy_hub.robot_voice.VoiceSession`), never persisted as session
authorization.

Freshness uses monotonic time throughout: the Nano's known RTC/pre-NTP clock
issues (HANDOVER.md) must not be able to extend or fabricate evidence.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

# Matches Phase 24g's WakeLimits.follow_up_seconds default
# (shared/models/robot_voice.py): when the follow-up window expires, T1/T2
# are discarded along with the session, so the two timers are kept equal.
FOLLOW_UP_TIMEOUT_SECONDS = 10.0

# Personal/private reads require speaker verification of the *current*
# utterance, not merely T1 carry-forward (docs/phase-25.md "Sensitive-request
# freshness").
SENSITIVE_REQUEST_REQUIRE_CURRENT_VOICE = True


class TrustLevel(StrEnum):
    """Ordered T0 (lowest) to T3 (highest); see docs/phase-25.md's trust
    table for the permissions each level typically carries. Ordering matters
    for callers that compare levels, so keep members in this order."""

    T0 = "t0"
    T1 = "t1"
    T2 = "t2"
    T3 = "t3"


_TRUST_ORDER = {level: index for index, level in enumerate(TrustLevel)}


def trust_at_least(trust: TrustLevel, minimum: TrustLevel) -> bool:
    return _TRUST_ORDER[trust] >= _TRUST_ORDER[minimum]


class SpeakerEvidence(BaseModel):
    """Phase 25a owner-speaker verification result for one utterance.
    `accepted` is the verifier's own accept/reject decision (quality,
    threshold, spoof check already folded in); the trust engine additionally
    checks `quality_ok`/`spoof_check` directly per docs/phase-25.md, since a
    verifier bug should not be the only thing standing between a rejected
    sample and T1."""

    owner_id: str
    robot_id: str
    voice_session_id: str
    turn: int

    captured_monotonic: float
    expires_monotonic: float

    model_version: str
    calibration_version: str

    similarity_score: float
    calibrated_confidence: float | None = None

    quality_ok: bool
    spoof_check: Literal["pass", "fail", "unavailable"]

    accepted: bool

    def fresh(self, now: float) -> bool:
        return now < self.expires_monotonic

    def qualifies(self, now: float) -> bool:
        return (
            self.fresh(now)
            and self.accepted
            and self.quality_ok
            and self.spoof_check != "fail"
        )


class VisualEvidence(BaseModel):
    """Phase 25b owner-face verification result for one observation.
    `doa_consistent` is `None` until sound-direction association is
    implemented (Phase 25b.1); `False` is a positive disagreement signal and
    blocks T2, `True`/`None` do not."""

    owner_id: str
    robot_id: str
    voice_session_id: str

    captured_monotonic: float
    expires_monotonic: float

    frame_sequence: int

    model_version: str
    calibration_version: str

    calibrated_confidence: float | None = None

    quality_ok: bool
    liveness_ok: bool
    frozen_frame: bool

    doa_consistent: bool | None = None

    accepted: bool

    def fresh(self, now: float) -> bool:
        return now < self.expires_monotonic

    def qualifies(self, now: float) -> bool:
        return (
            self.fresh(now)
            and self.accepted
            and self.quality_ok
            and self.liveness_ok
            and not self.frozen_frame
            and self.doa_consistent is not False
        )


class TrustLimits(BaseModel):
    """Operating hypotheses (docs/phase-25.md), to validate on hardware and
    change only from recorded evidence, never convenience alone."""

    voice_ttl_seconds: float = 10.0
    visual_ttl_seconds: float = 1.0

    visual_initial_hits: int = 3
    visual_initial_span_ms: int = 500

    sensitive_playback_loss_ms: int = 1000
