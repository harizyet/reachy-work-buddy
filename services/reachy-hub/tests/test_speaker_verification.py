"""Phase 25a.3: speaker verification wired into robot voice turns
(docs/phase-25.md's "Integration into RobotVoiceManager"). Runs
concurrently with STT on the same WAV and attaches the result to the
session's VoiceTrustContext -- never a second biometric-session store."""

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
from reachy_hub.speaker.base import NoSpeakerVerifier

from shared.models.robot_voice import VOICE_CAPABILITY
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


def _evidence(**overrides) -> SpeakerEvidence:
    fields = {
        "owner_id": "owner",
        "robot_id": ROBOT_ID,
        "voice_session_id": "session-1",
        "turn": 1,
        "captured_monotonic": 0.0,
        "expires_monotonic": 100.0,
        "model_version": "fake-1",
        "calibration_version": "cal-1",
        "similarity_score": 0.9,
        "calibrated_confidence": 0.95,
        "quality_ok": True,
        "spoof_check": "pass",
        "accepted": True,
    }
    fields.update(overrides)
    return SpeakerEvidence(**fields)


def build_pipeline(*transcripts: str, verify_speaker=None) -> VoiceTurnPipeline:
    remaining = list(transcripts)

    async def transcribe(_):
        return remaining.pop(0)

    async def converse(user_id, text):
        return ConversationReply(reply=f"reply to {text}", delivery_channel=Channel.REACHY)

    async def flags(_):
        return False, PrivacyContext.UNKNOWN

    async def synthesize(text):
        return b"audio"

    async def deliver(*_):
        return False

    kwargs = {"verify_speaker": verify_speaker} if verify_speaker is not None else {}
    return VoiceTurnPipeline(transcribe, converse, flags, synthesize, deliver, robot_speech_withheld_reason, **kwargs)


def test_default_pipeline_never_produces_speaker_evidence() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    manager.begin_turn(ROBOT_ID, 1, session.voice_session_id, 1)
    pipeline = build_pipeline("what time is it")

    outcome, _ = asyncio.run(run_turn(manager, session, 1, b"wav-bytes", pipeline))

    assert session.trust.speaker is None
    assert outcome.value == "spoken"


def test_verify_speaker_runs_and_attaches_evidence_to_session_trust() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    manager.begin_turn(ROBOT_ID, 1, session.voice_session_id, 1)
    seen_kwargs = {}

    async def verify(wav_bytes, **kwargs):
        seen_kwargs.update(kwargs)
        seen_kwargs["wav_bytes"] = wav_bytes
        return _evidence(voice_session_id=session.voice_session_id)

    pipeline = build_pipeline("what time is it", verify_speaker=verify)

    asyncio.run(run_turn(manager, session, 1, b"wav-bytes", pipeline))

    assert session.trust.speaker is not None
    assert session.trust.speaker.voice_session_id == session.voice_session_id
    assert seen_kwargs == {
        "wav_bytes": b"wav-bytes",
        "owner_id": session.user_id,
        "robot_id": ROBOT_ID,
        "voice_session_id": session.voice_session_id,
        "turn": 1,
    }


def test_speaker_verification_failure_does_not_fail_the_turn() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    manager.begin_turn(ROBOT_ID, 1, session.voice_session_id, 1)

    async def broken_verify(*_args, **_kwargs):
        raise RuntimeError("model crashed")

    pipeline = build_pipeline("what time is it", verify_speaker=broken_verify)

    outcome, _ = asyncio.run(run_turn(manager, session, 1, b"wav-bytes", pipeline))

    assert outcome.value == "spoken"
    assert session.trust.speaker is None


def test_transcription_failure_still_fails_the_turn() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    manager.begin_turn(ROBOT_ID, 1, session.voice_session_id, 1)

    async def transcribe(_):
        raise RuntimeError("stt crashed")

    async def verify(*_args, **_kwargs):
        return _evidence()

    pipeline = build_pipeline(verify_speaker=verify)
    pipeline.transcribe = transcribe

    outcome, _ = asyncio.run(run_turn(manager, session, 1, b"wav-bytes", pipeline))

    assert outcome.value == "failed"
    # The gather never completed, so the assignment to session.trust.speaker
    # never happened -- it stays at its initial default, not the verifier's
    # (successful) result.
    assert session.trust.speaker is None


def test_pretranscribed_wake_admission_turn_still_runs_speaker_verification() -> None:
    manager = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    session.pretranscribed = "what time is it"
    manager.begin_turn(ROBOT_ID, 1, session.voice_session_id, 1, 1)
    calls: list[bytes] = []

    async def verify(wav_bytes, **_kwargs):
        calls.append(wav_bytes)
        return _evidence()

    pipeline = build_pipeline(verify_speaker=verify)

    asyncio.run(run_turn(manager, session, 1, b"wav-bytes", pipeline, segment=1))

    assert calls == [b"wav-bytes"]
    assert session.trust.speaker is not None


def test_no_speaker_verifier_default_returns_none() -> None:
    result = asyncio.run(
        NoSpeakerVerifier().verify(
            b"wav-bytes", owner_id="owner", robot_id=ROBOT_ID, voice_session_id="s", turn=1
        )
    )
    assert result is None
