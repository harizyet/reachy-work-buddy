"""Phase 25a.4: the input-sensitivity gate wired into robot voice turns
(docs/phase-25.md). Off by default (VoiceTurnPipeline.sensitivity_gate_enabled
defaults to False) -- these tests exercise it explicitly enabled."""

from __future__ import annotations

import asyncio

from reachy_hub.response_policy import robot_speech_withheld_reason
from reachy_hub.robot_connection_manager import RobotConnectionManager
from reachy_hub.robot_voice import (
    ConversationReply,
    RobotVoiceManager,
    VoiceTurnPipeline,
    run_turn,
)

from shared.models.robot_voice import VOICE_CAPABILITY, VoiceTurnOutcome
from shared.models.session import Channel, PrivacyContext
from shared.models.trust import SpeakerEvidence

ROBOT_ID = "robot-1"


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class RecordingSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def make_manager():
    connections = RobotConnectionManager()
    socket = RecordingSocket()
    asyncio.run(connections.register(ROBOT_ID, socket, capabilities=[VOICE_CAPABILITY], sim=True))
    manager = RobotVoiceManager(connections, clock=Clock())
    return manager


def _fresh_speaker_evidence(session, *, now: float) -> SpeakerEvidence:
    return SpeakerEvidence(
        owner_id=session.user_id,
        robot_id=ROBOT_ID,
        voice_session_id=session.voice_session_id,
        turn=1,
        captured_monotonic=now,
        expires_monotonic=now + 10.0,
        model_version="fake-1",
        calibration_version="cal-1",
        similarity_score=0.9,
        calibrated_confidence=0.95,
        quality_ok=True,
        spoof_check="pass",
        accepted=True,
    )


def build_pipeline(*transcripts: str, verify_speaker=None, gate=True) -> VoiceTurnPipeline:
    remaining = list(transcripts)

    async def transcribe(_):
        return remaining.pop(0)

    conversed: list[str] = []

    async def converse(user_id, text):
        conversed.append(text)
        return ConversationReply(reply=f"reply to {text}", delivery_channel=Channel.REACHY)

    async def flags(_):
        return False, PrivacyContext.UNKNOWN

    async def synthesize(text):
        return b"audio"

    async def deliver(*_):
        return False

    kwargs = {"verify_speaker": verify_speaker} if verify_speaker is not None else {}
    pipeline = VoiceTurnPipeline(
        transcribe, converse, flags, synthesize, deliver, robot_speech_withheld_reason,
        sensitivity_gate_enabled=gate, **kwargs,
    )
    pipeline.conversed = conversed  # type: ignore[attr-defined]
    return pipeline


def run(manager, session, transcript, *, verify_speaker=None, gate=True):
    manager.begin_turn(ROBOT_ID, 1, session.voice_session_id, 1)
    pipeline = build_pipeline(transcript, verify_speaker=verify_speaker, gate=gate)
    outcome, _ = asyncio.run(run_turn(manager, session, 1, b"wav-bytes", pipeline))
    return outcome, pipeline


def test_gate_disabled_by_default_reaches_core_regardless_of_sensitivity() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    outcome, pipeline = run(manager, session, "read my email", gate=False)
    assert outcome == VoiceTurnOutcome.SPOKEN
    assert pipeline.conversed == ["read my email"]


def test_public_request_reaches_core_even_at_t0() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    outcome, pipeline = run(manager, session, "what time is it")
    assert outcome == VoiceTurnOutcome.SPOKEN
    assert pipeline.conversed == ["what time is it"]


def test_personal_request_at_t0_is_withheld_before_reaching_core() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    outcome, pipeline = run(manager, session, "read my email")
    assert outcome == VoiceTurnOutcome.WITHHELD
    assert pipeline.conversed == []
    assert "verification" in session.turns[-1].reason.lower()


def test_personal_request_at_t1_is_still_withheld_no_visual_verifier_yet() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))

    async def verify(*_args, **_kwargs):
        return _fresh_speaker_evidence(session, now=manager.now())

    outcome, pipeline = run(manager, session, "read my email", verify_speaker=verify)
    assert outcome == VoiceTurnOutcome.WITHHELD
    assert pipeline.conversed == []


def test_unknown_sensitivity_is_withheld_at_t0() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    outcome, pipeline = run(manager, session, "how tall is mount everest")
    assert outcome == VoiceTurnOutcome.WITHHELD
    assert pipeline.conversed == []
