"""Transport-neutral voice-identity evidence and profile metadata (Phase 32A,
ADR 0041). The robot-shaped `trust.SpeakerEvidence` stays as it is for the robot
voice path; `VoiceEvidence` carries the same facts for any client (phone, web,
robot) with device, client and session provenance, and converts to the robot type
on request. Evidence is identity evidence only: nothing here authorizes anything
(ADR 0024), and a raw similarity score never leaves the hub in an API response."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from shared.models.trust import SpeakerEvidence

# Both the hub and the speaker sidecar need the same audio contract.
AUDIO_SAMPLE_RATE = 16000
MAX_AUDIO_BYTES = 2 * 1024 * 1024


class VoiceState(StrEnum):
    VERIFIED = "verified"
    UNCERTAIN = "uncertain"
    NOT_VERIFIED = "not_verified"
    UNAVAILABLE = "unavailable"  # no profile, disabled, model outage, unusable audio: never a rejection


class ClientKind(StrEnum):
    ANDROID = "android"
    WEB = "web"
    ROBOT = "robot"


class ClientProvenance(BaseModel):
    """Who captured the audio. `client_id` and `device_id` are asserted by the client
    (an install id); they are provenance for audit and binding, not authentication."""

    client_kind: ClientKind
    client_id: str = Field(min_length=1, max_length=64)
    device_id: str | None = Field(default=None, max_length=64)


class VoiceEvidence(BaseModel):
    evidence_id: str
    utterance_id: str
    owner_id: str
    client: ClientProvenance
    # The authenticated session that submitted the audio. None until per-device
    # server-side sessions exist (Phase 32A.1); binding then falls back to the client id.
    session_id: str | None = None
    turn: int | None = None

    issued_monotonic: float
    expires_monotonic: float
    issued_at: datetime
    expires_at: datetime

    model_version: str
    calibration_version: str
    profile_id: str | None = None
    profile_version: int | None = None

    similarity_score: float | None = None
    quality_ok: bool
    quality_reasons: list[str] = Field(default_factory=list)
    spoof_check: Literal["pass", "fail", "unavailable"] = "unavailable"

    state: VoiceState

    def fresh(self, now: float) -> bool:
        return now < self.expires_monotonic

    def qualifies(self, now: float) -> bool:
        return self.fresh(now) and self.state == VoiceState.VERIFIED and self.quality_ok and self.spoof_check != "fail"

    def to_speaker_evidence(self, *, robot_id: str, voice_session_id: str, turn: int) -> SpeakerEvidence | None:
        """The robot-shaped record, for a caller that already speaks `SpeakerVerifier`. None
        when there is no score to report (unavailable); the robot path then caps at T0."""
        if self.similarity_score is None:
            return None
        return SpeakerEvidence(
            owner_id=self.owner_id, robot_id=robot_id, voice_session_id=voice_session_id, turn=turn,
            captured_monotonic=self.issued_monotonic, expires_monotonic=self.expires_monotonic,
            model_version=self.model_version, calibration_version=self.calibration_version,
            similarity_score=self.similarity_score, quality_ok=self.quality_ok, spoof_check=self.spoof_check,
            accepted=self.state == VoiceState.VERIFIED,
        )


class VoiceStateView(BaseModel):
    """What a client sees: a state and an expiry, never the score or the template."""

    state: VoiceState
    utterance_id: str
    issued_at: datetime
    expires_at: datetime
    expires_in_seconds: float
    reasons: list[str] = Field(default_factory=list)
    replay_protection: Literal["none"] = "none"  # no anti-spoof model exists; the UI must not claim otherwise


class ProfileInfo(BaseModel):
    profile_id: str
    label: str
    version: int
    model_version: str
    sample_count: int
    created_at: datetime
    enrolled_by: ClientProvenance


class EnrollmentSampleView(BaseModel):
    sample_id: str
    quality_ok: bool
    reasons: list[str] = Field(default_factory=list)
    speech_seconds: float


class EnrollmentDraftView(BaseModel):
    samples: list[EnrollmentSampleView]
    usable_samples: int
    required_samples: int
    expires_in_seconds: float


class VoiceIdentityStatus(BaseModel):
    enabled: bool
    ready: bool  # the embedding service answers
    profile: ProfileInfo | None = None
    draft: EnrollmentDraftView | None = None
    reauthenticated: bool = False
    model_version: str | None = None
    calibration_version: str
    calibrated: bool
