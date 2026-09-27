"""Robot microphone/speaker conversation contract (Phase 24c, ADR 0023).

Shared by reachy-hub (session owner, STT/TTS, routing) and
reachy-embodiment (capture, turn detection, playback). Limits are defaults
sent to the robot in `voice_start`; the hub enforces its own copies.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from shared.models.websearch import TurnWebSearch

# Capability a robot advertises at WSS registration when it can capture.
VOICE_CAPABILITY = "voice_conversation"
# Advertised alongside it when the robot can continue a held turn (Phase
# 24e, ADR 0023 adaptive end of turn); the hub holds only for such robots.
VOICE_CONTINUATION_CAPABILITY = "voice_turn_continuation"
# Advertised by a robot that can monitor for the spoken wake phrase (Phase
# 24g, ADR 0023 wake-started sessions).
WAKE_CAPABILITY = "wake_admission"

SAMPLE_RATE = 16000
# 30 s of 16 kHz mono 16-bit PCM is 960 KB; the cap leaves header slack.
MAX_UTTERANCE_BYTES = 1024 * 1024
# A held turn is continued only while at least this much of the merged
# turn's `max_utterance_seconds` remains.
MIN_CONTINUATION_SECONDS = 1.0
# Open-palm stop (Phase 24e item 5): the robot downscales frames to this
# width before upload, and the hub refuses anything larger than the cap.
PALM_FRAME_MAX_WIDTH = 640
MAX_PALM_FRAME_BYTES = 256 * 1024

# Upload headers (robot -> hub). Identity/credential use ADR 0019's
# X-Robot-Id + Authorization headers.
ROBOT_GENERATION_HEADER = "X-Robot-Generation"
VOICE_SESSION_HEADER = "X-Voice-Session"
VOICE_TURN_HEADER = "X-Voice-Turn"
# 1-based segment of a held turn; absent means 1.
VOICE_SEGMENT_HEADER = "X-Voice-Segment"
VOICE_OUTCOME_HEADER = "X-Voice-Turn-Outcome"
# The arm a wake candidate was captured under; a stale arm is refused.
WAKE_ARM_HEADER = "X-Wake-Arm"


class VoiceLimits(BaseModel):
    # Bounds the whole turn, including every segment of a held turn.
    max_utterance_seconds: float = Field(30.0, gt=0, le=30)
    end_of_speech_silence_ms: int = Field(700, ge=100, le=3000)
    min_utterance_ms: int = Field(300, ge=0, le=5000)
    pre_roll_ms: int = Field(300, ge=0, le=1000)
    playback_tail_guard_ms: int = Field(400, ge=0, le=3000)
    max_session_seconds: float = Field(600.0, gt=0, le=3600)
    # After a `continue`, how long the robot waits, from the segment cut,
    # for speech to start again before asking the hub to answer. 0 disables
    # holding.
    continuation_window_ms: int = Field(1500, ge=0, le=5000)


class WakeLimits(BaseModel):
    """Phase 24g candidate bounds, sent to the robot in `wake_arm`.
    Calibration defaults; see docs/phase-24g.md."""

    # Detector score that starts a candidate.
    detection_threshold: float = Field(0.7, gt=0, le=1)
    # A first segment with less speech than this (pre-roll and trailing
    # silence not counted) is taken to hold only the wake phrase, so the
    # robot waits for the request that follows it.
    min_request_seconds: float = Field(1.2, ge=0, le=5)
    # How long after the wake phrase's segment ends the request may start.
    # Raised from 4.0 (owner, 2026-09-27, phase 24g Session 2): a genuine
    # attempt was discarded because noticing the alert-pose cue and then
    # starting to speak took most of the 4 s budget.
    speech_start_seconds: float = Field(6.0, gt=0, le=10)
    # Cap on the whole candidate, wake phrase included.
    max_candidate_seconds: float = Field(10.0, gt=0, le=15)
    # A wake-started session ends when no speech starts this long after
    # the robot starts listening again.
    follow_up_seconds: float = Field(10.0, gt=0, le=60)


class WakeAdmission(BaseModel):
    """Hub -> robot answer to an admitted wake candidate. The hub also
    sends `voice_start` for the session over the control socket."""

    voice_session_id: str


class PalmFrameResult(BaseModel):
    """Hub -> robot answer to one palm-stop frame. `stop` means an open
    palm was held long enough: stop this reply and listen again."""

    stop: bool


class RobotVoiceState(StrEnum):
    LISTENING = "listening"
    UPLOADING = "uploading"
    SPEAKING = "speaking"
    STOPPED = "stopped"
    ERROR = "error"


class VoiceSessionState(StrEnum):
    """Hub-side state shown to the owner."""

    STARTING = "starting"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    STOPPED = "stopped"


class VoiceTurnOutcome(StrEnum):
    SPOKEN = "spoken"
    WITHHELD = "withheld"
    NO_SPEECH = "no_speech"
    CANCELLED = "cancelled"
    FAILED = "failed"
    # The segment sounded unfinished; the hub holds it and the robot keeps
    # listening. Never recorded as a turn.
    CONTINUE = "continue"
    # Phase 24g: a wake candidate the hub did not admit. Never recorded.
    REJECTED = "rejected"


class VoiceTurnRecord(BaseModel):
    """One completed turn, kept in hub memory for the owner's panel only
    while the session record exists; never logged."""

    turn: int
    transcript: str | None = None
    reply: str | None = None
    web_search: TurnWebSearch | None = None
    outcome: VoiceTurnOutcome
    reason: str | None = None
    # Segments merged into this turn by adaptive end of turn.
    segments: int = 1
    # Stage durations for latency measurement (Phase 24d). A stage that did
    # not run, because the turn ended earlier, stays None.
    received_at: datetime | None = None
    transcription_ms: int | None = None
    conversation_ms: int | None = None
    synthesis_ms: int | None = None


class VoiceSessionStatus(BaseModel):
    voice_session_id: str
    robot_id: str
    user_id: str
    state: VoiceSessionState
    stop_reason: str | None = None
    last_error: str | None = None
    next_turn: int
    lease_seconds_remaining: float
    session_seconds_remaining: float
    turns: list[VoiceTurnRecord] = []
    # Opened by the spoken wake phrase rather than the owner's control;
    # such a session has no owner lease.
    wake_started: bool = False


class WakeCounts(BaseModel):
    """Content-free admission counters since the hub started (Phase 24g
    per-hour metrics). Rejections are keyed by reason."""

    candidates: int = 0
    admitted: int = 0
    rejected: dict[str, int] = {}


class RobotVoiceAvailability(BaseModel):
    robot_id: str
    online: bool
    voice_capable: bool
    wake_capable: bool = False
    wake_armed: bool = False
    wake_counts: WakeCounts = WakeCounts()


class VoiceOverview(BaseModel):
    robots: list[RobotVoiceAvailability]
    session: VoiceSessionStatus | None = None


class StartVoiceRequest(BaseModel):
    robot_id: str
    user_id: str | None = None


class WakeArmRequest(BaseModel):
    robot_id: str
    armed: bool
    user_id: str | None = None


class VoiceSessionRef(BaseModel):
    voice_session_id: str
