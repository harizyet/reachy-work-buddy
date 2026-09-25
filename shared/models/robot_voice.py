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


class RobotVoiceAvailability(BaseModel):
    robot_id: str
    online: bool
    voice_capable: bool


class VoiceOverview(BaseModel):
    robots: list[RobotVoiceAvailability]
    session: VoiceSessionStatus | None = None


class StartVoiceRequest(BaseModel):
    robot_id: str
    user_id: str | None = None


class VoiceSessionRef(BaseModel):
    voice_session_id: str
