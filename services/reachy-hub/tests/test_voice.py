"""POST /voice/turn, end to end, with real (not mocked) STT and TTS: a
synthesized WAV question goes in, a real transcription happens, the text
flows through the exact same handle_inbound_message path every other
channel uses, and a real synthesized WAV reply comes back out — the Phase 8
exit criterion ("Reachy conversation works without Jarvis monolithic
loop"), fully automated.
"""

from __future__ import annotations

import io
import shutil
import wave

import httpx
import pytest
from companion_core.app import create_app as _create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.tasks.store import InMemoryTaskStore
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.stt import FasterWhisperSTT
from reachy_hub.tts import EspeakTTS

espeak_binary = shutil.which("espeak-ng")


def create_core_app(**kwargs):
    kwargs.setdefault("calendar_store", InMemoryCalendarStore())
    kwargs.setdefault("task_store", InMemoryTaskStore())
    return _create_core_app(**kwargs)


def make_hub_client(**kwargs) -> TestClient:
    embodiment_app = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    core_app = create_core_app()
    app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        companion_core_client=CompanionCoreClient(
            "http://companion-core", transport=httpx.ASGITransport(app=core_app)
        ),
        run_heartbeat_task=False,
        **kwargs,
    )
    return TestClient(app)


def _synthesize_wav(text: str) -> bytes:
    return EspeakTTS().synthesize(text)


def _wav_is_well_formed(data: bytes) -> bool:
    with wave.open(io.BytesIO(data)) as wav_file:
        return wav_file.getnframes() > 0


@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_voice_turn_transcribes_synthesizes_and_uses_the_same_session_pipeline() -> None:
    client = make_hub_client(stt_factory=lambda: FasterWhisperSTT(model_size="tiny.en"), tts_factory=EspeakTTS)

    question_wav = _synthesize_wav("what is on my calendar today")
    resp = client.post(
        "/voice/turn",
        data={"user_id": "hariz"},
        files={"audio": ("question.wav", question_wav, "audio/wav")},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert "calendar" in resp.headers["x-transcript"].lower()
    assert "turn 1" in resp.headers["x-reply-text"]
    assert _wav_is_well_formed(resp.content)

    # It went through the real channel-agnostic session pipeline: same
    # GET /sessions/{user_id} observability every other channel gets.
    session = client.get("/sessions/hariz").json()
    assert session["active_channel"] == "reachy"


@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_voice_turn_continues_a_session_started_over_text() -> None:
    """The Reachy voice channel and the text /messages endpoint share one
    session — voice is just another way to reach the same conversation."""
    client = make_hub_client(stt_factory=lambda: FasterWhisperSTT(model_size="tiny.en"), tts_factory=EspeakTTS)

    text_resp = client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hello there"})
    session_id = text_resp.json()["session_id"]

    question_wav = _synthesize_wav("continue our conversation please")
    voice_resp = client.post(
        "/voice/turn",
        data={"user_id": "hariz"},
        files={"audio": ("question.wav", question_wav, "audio/wav")},
    )

    assert "turn 2" in voice_resp.headers["x-reply-text"]
    assert client.get("/sessions/hariz").json()["session_id"] == session_id


@pytest.mark.slow
def test_voice_turn_rejects_silence() -> None:
    client = make_hub_client(stt_factory=lambda: FasterWhisperSTT(model_size="tiny.en"))

    silence = io.BytesIO()
    with wave.open(silence, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000)

    resp = client.post(
        "/voice/turn",
        data={"user_id": "hariz"},
        files={"audio": ("silence.wav", silence.getvalue(), "audio/wav")},
    )
    assert resp.status_code == 422
