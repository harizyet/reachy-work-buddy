"""Phase 24c robot microphone conversation, hub side (ADR 0023).

Lifecycle tests drive RobotVoiceManager with a controlled clock and a
recording socket. Integration tests run the real hub app in process with
a robot WSS connection (TestClient), the real companion-core app over
ASGITransport, and scripted STT/TTS stand-ins; real speech providers are
exercised in the `slow` test at the bottom. None of this is hardware.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import time
import wave

import httpx
import pytest
from companion_core.app import create_app as _create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_connection_manager import RobotConnectionManager
from reachy_hub.robot_credential_store import InMemoryRobotCredentialStore
from reachy_hub.robot_registry import InMemoryRobotRegistry, Robot
from reachy_hub.robot_voice import (
    ConversationReply,
    RobotVoiceManager,
    VoiceSessionError,
    VoiceTurnPipeline,
    run_turn,
)
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

from shared.models.robot_voice import (
    MAX_UTTERANCE_BYTES,
    VOICE_CAPABILITY,
    RobotVoiceState,
    VoiceLimits,
    VoiceSessionState,
    VoiceTurnOutcome,
)
from shared.models.robot_ws import VoiceStateMessage, WSMessageType
from shared.models.session import Channel, PrivacyContext
from shared.protocols.robot_ws import PROTOCOL_VERSION, ROBOT_VOICE_TURN, ROBOTS_CONNECT

ROBOT_ID = "nano-1"
ROBOT_TOKEN = "robot-secret"
OWNER = {"Authorization": "Bearer owner-token"}
CSRF = {"X-Reachy-CSRF": "1"}
espeak_binary = shutil.which("espeak-ng")


def wav_bytes(seconds: float = 0.5, rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x01\x00" * int(seconds * rate) * channels)
    return buf.getvalue()


# --- lifecycle, controlled time ------------------------------------------


class RecordingSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, data: object) -> None:
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(data)  # type: ignore[arg-type]

    async def close(self, code: int = 1000) -> None:
        pass


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_manager(*, capabilities=(VOICE_CAPABILITY,), socket=None, **kwargs):
    connections = RobotConnectionManager()
    socket = socket or RecordingSocket()
    connection = asyncio.run(connections.register(ROBOT_ID, socket, capabilities=list(capabilities), sim=True))
    clock = Clock()
    manager = RobotVoiceManager(connections, clock=clock, **kwargs)
    return manager, connections, connection, socket, clock


def test_start_requires_a_connected_voice_capable_robot() -> None:
    manager, _, _, _, _ = make_manager(capabilities=())
    with pytest.raises(VoiceSessionError, match="not enabled"):
        asyncio.run(manager.start(ROBOT_ID, "owner"))
    with pytest.raises(VoiceSessionError, match="not connected"):
        asyncio.run(manager.start("other-robot", "owner"))


def test_start_sends_voice_start_and_robot_report_moves_to_listening() -> None:
    manager, _, connection, socket, _ = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))

    assert socket.sent[0]["type"] == WSMessageType.VOICE_START
    assert socket.sent[0]["voice_session_id"] == session.voice_session_id
    assert session.state == VoiceSessionState.STARTING

    report = VoiceStateMessage(voice_session_id=session.voice_session_id, state=RobotVoiceState.LISTENING)
    asyncio.run(manager.on_robot_message(connection, report.model_dump(mode="json")))
    assert session.state == VoiceSessionState.LISTENING

    # A second start from the same owner is idempotent, not a new session.
    assert asyncio.run(manager.start(ROBOT_ID, "owner")) is session
    with pytest.raises(VoiceSessionError, match="already"):
        asyncio.run(manager.start(ROBOT_ID, "someone-else"))


def test_unreachable_robot_fails_start_without_leaving_an_active_session() -> None:
    manager, _, _, _, _ = make_manager(socket=RecordingSocket(fail=True))
    with pytest.raises(VoiceSessionError) as excinfo:
        asyncio.run(manager.start(ROBOT_ID, "owner"))
    assert excinfo.value.status_code == 502
    assert manager.overview([]).session.state == VoiceSessionState.STOPPED


def test_lease_lapse_stops_and_tells_the_robot() -> None:
    manager, _, _, socket, clock = make_manager(lease_seconds=15)
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))

    clock.now += 10
    manager.renew(session.voice_session_id)
    clock.now += 10
    asyncio.run(manager.expire())
    assert session.active  # renewed 10 s ago, lease is 15 s

    clock.now += 6
    asyncio.run(manager.expire())
    assert not session.active
    assert session.stop_reason == "Owner control stopped responding"
    assert socket.sent[-1] == {
        "type": "voice_stop", "voice_session_id": session.voice_session_id, "reason": session.stop_reason,
    }
    # Renewing a stopped session never revives it.
    manager.renew(session.voice_session_id)
    assert not session.active


def test_maximum_duration_and_idle_timeout() -> None:
    manager, _, _, _, clock = make_manager(
        lease_seconds=10_000, idle_timeout_seconds=120, limits=VoiceLimits(max_session_seconds=600)
    )
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    clock.now += 119
    asyncio.run(manager.expire())
    assert session.active
    clock.now += 2
    asyncio.run(manager.expire())
    assert session.stop_reason == "No speech heard for a while"

    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    started = clock.now
    while session.active:  # stay busy so the idle timeout never fires
        clock.now += 100
        manager.begin_turn(ROBOT_ID, 1, session.voice_session_id, session.next_turn)
        asyncio.run(manager.expire())
        session.in_flight_turn = None
    assert session.stop_reason == "Maximum conversation length reached"
    assert clock.now - started == 600


def test_turn_validation_and_fencing() -> None:
    manager, connections, connection, _, _ = make_manager()
    session = asyncio.run(manager.start(ROBOT_ID, "owner"))
    sid = session.voice_session_id

    with pytest.raises(VoiceSessionError, match="No active"):
        manager.begin_turn(ROBOT_ID, 1, "wrong-session", 1)
    with pytest.raises(VoiceSessionError, match="Stale"):
        manager.begin_turn(ROBOT_ID, 99, sid, 1)
    manager.begin_turn(ROBOT_ID, 1, sid, 1)
    assert session.state == VoiceSessionState.THINKING
    with pytest.raises(VoiceSessionError, match="already in progress"):
        manager.begin_turn(ROBOT_ID, 1, sid, 2)
    session.in_flight_turn = None
    with pytest.raises(VoiceSessionError, match="Unexpected turn"):
        manager.begin_turn(ROBOT_ID, 1, sid, 1)
    # A lost upload means the robot skips ahead; that is accepted.
    manager.begin_turn(ROBOT_ID, 1, sid, 3)
    assert session.next_turn == 4

    # A superseded connection's disconnect must not end the session of
    # the newer generation, but the current generation's disconnect does.
    newer = asyncio.run(connections.register(ROBOT_ID, RecordingSocket(), capabilities=[VOICE_CAPABILITY], sim=True))
    session.in_flight_turn = None
    session2 = asyncio.run(manager.start(ROBOT_ID, "owner"))
    assert session2 is session  # still active under generation 1
    asyncio.run(manager.stop(session, "test"))
    session3 = asyncio.run(manager.start(ROBOT_ID, "owner"))
    assert session3.generation == newer.generation
    asyncio.run(manager.on_robot_disconnect(connection))
    assert session3.active
    asyncio.run(manager.on_robot_disconnect(newer))
    assert session3.stop_reason == "Robot disconnected"


def test_stop_mid_turn_discards_the_late_reply() -> None:
    manager, _, _, socket, _ = make_manager()
    released = asyncio.Event()
    calls: list[str] = []

    async def slow_converse(user_id, text):
        calls.append(text)
        await released.wait()
        return ConversationReply(reply="late reply", delivery_channel=Channel.REACHY)

    async def synthesize(text):
        calls.append("tts")
        return b"audio"

    async def transcribe(_):
        return "hello"

    async def flags(_):
        return False, PrivacyContext.UNKNOWN

    async def deliver(*_):
        return False

    from reachy_hub.response_policy import robot_speech_withheld_reason

    pipeline = VoiceTurnPipeline(transcribe, slow_converse, flags, synthesize, deliver, robot_speech_withheld_reason)

    async def scenario():
        session = await manager.start(ROBOT_ID, "owner")
        manager.begin_turn(ROBOT_ID, 1, session.voice_session_id, 1)
        task = asyncio.create_task(run_turn(manager, session, 1, b"", pipeline))
        await asyncio.sleep(0)
        await manager.stop(session, "Stopped by owner")
        released.set()
        return session, await task

    session, (outcome, audio) = asyncio.run(scenario())
    assert (outcome, audio) == (VoiceTurnOutcome.CANCELLED, None)
    assert "tts" not in calls  # never synthesized, let alone played
    assert socket.sent[-1]["type"] == "voice_stop"
    assert session.turns[-1].outcome == VoiceTurnOutcome.CANCELLED


# --- in-process hub/core chain -------------------------------------------


class ScriptedSTT:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0

    def transcribe(self, wav: bytes) -> str:
        self.calls += 1
        return self.texts.pop(0)


class RecordingTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.spoken.append(text)
        return wav_bytes(0.1)


def create_core_app():
    return _create_core_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
    )


def make_hub(stt, tts, **kwargs):
    credentials = InMemoryRobotCredentialStore()
    credentials.provision(ROBOT_ID, ROBOT_TOKEN)
    embodiment = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    registry = InMemoryRobotRegistry()
    asyncio.run(registry.register(Robot(robot_id=ROBOT_ID, base_url="http://embodiment")))
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    app = create_app(
        registry=registry,
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
        client_factory=lambda url: EmbodimentClient(url, transport=httpx.ASGITransport(app=embodiment)),
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=create_core_app())),
        run_heartbeat_task=False,
        run_telegram_poll_task=False,
        run_voice_watchdog_task=False,
        robot_credential_store=credentials,
        robot_ws_heartbeat_interval=30,
        robot_ws_watchdog_timeout=60,
        remote_ui_token="owner-token",
        user_store=users,
        session_secret_key="test-session-secret",
        stt=stt,
        tts=tts,
        **kwargs,
    )
    return TestClient(app), app, embodiment


def connect_robot(client, capabilities=(VOICE_CAPABILITY,)):
    ws = client.websocket_connect(ROBOTS_CONNECT, headers={"X-Robot-Id": ROBOT_ID, "Authorization": f"Bearer {ROBOT_TOKEN}"})
    socket = ws.__enter__()
    socket.send_json({
        "type": "register", "robot_id": ROBOT_ID, "protocol_version": PROTOCOL_VERSION,
        "capabilities": list(capabilities), "sim": True,
    })
    registered = socket.receive_json()
    return ws, socket, registered["generation"]


def wait_for_state(client, state: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        session = client.get("/robot-voice", headers=OWNER).json()["session"]
        if session and session["state"] == state:
            return session
        assert time.monotonic() < deadline, f"voice session never reached {state}: {session}"
        time.sleep(0.02)


def start_listening(client, socket) -> str:
    status = client.post("/robot-voice/start", json={"robot_id": ROBOT_ID}, headers=OWNER)
    assert status.status_code == 200, status.text
    start = socket.receive_json()
    assert start["type"] == "voice_start"
    assert start["limits"]["max_utterance_seconds"] == 15.0
    socket.send_json({"type": "voice_state", "voice_session_id": start["voice_session_id"], "state": "listening"})
    wait_for_state(client, "listening")
    return start["voice_session_id"]


def upload(client, sid, turn, generation, body=None, token=ROBOT_TOKEN):
    return client.post(
        ROBOT_VOICE_TURN,
        content=body if body is not None else wav_bytes(),
        headers={
            "X-Robot-Id": ROBOT_ID, "Authorization": f"Bearer {token}", "X-Robot-Generation": str(generation),
            "X-Voice-Session": sid, "X-Voice-Turn": str(turn), "Content-Type": "audio/wav",
        },
    )


def test_spoken_turns_share_the_conversation_with_web_chat() -> None:
    stt = ScriptedSTT("hello reachy", "and what did I just say")
    tts = RecordingTTS()
    client, _, _ = make_hub(stt, tts)
    with client:
        ws, socket, generation = connect_robot(client)
        try:
            sid = start_listening(client, socket)

            first = upload(client, sid, 1, generation)
            assert first.status_code == 200
            assert first.headers["x-voice-turn-outcome"] == "spoken"
            assert first.headers["content-type"] == "audio/wav"
            spoken = wait_for_state(client, "speaking")["turns"][0]
            assert spoken["transcript"] == "hello reachy"
            assert spoken["received_at"]
            assert all(spoken[stage] >= 0 for stage in ("transcription_ms", "conversation_ms", "synthesis_ms"))
            socket.send_json({"type": "voice_state", "voice_session_id": sid, "state": "listening"})
            wait_for_state(client, "listening")

            # Continue by typing in web chat, then speak again: one session,
            # one conversation (core's placeholder reply counts turns).
            typed = client.post("/messages", json={"user_id": "default-user", "channel": "web", "text": "typed turn"})
            assert "turn 2" in typed.json()["reply"]
            second = upload(client, sid, 2, generation)
            assert second.status_code == 200
            assert "turn 3" in tts.spoken[-1]
            session = client.get("/sessions/default-user").json()
            assert session["active_channel"] == "reachy"
            assert typed.json()["session_id"] == session["session_id"]
        finally:
            ws.__exit__(None, None, None)


def test_private_modes_withhold_speech_and_never_synthesize() -> None:
    stt = ScriptedSTT("tell me something", "what is on my calendar", "hello again", "hello once more")
    tts = RecordingTTS()
    client, _, _ = make_hub(stt, tts)
    with client:
        ws, socket, generation = connect_robot(client)
        try:
            sid = start_listening(client, socket)
            client.post("/messages", json={"user_id": "default-user", "channel": "web", "text": "hi"})

            client.patch("/sessions/default-user/mode", json={"interaction_mode": "office"}, headers=OWNER)
            office = upload(client, sid, 1, generation)
            assert (office.status_code, office.headers["x-voice-turn-outcome"]) == (204, "withheld")

            client.patch("/sessions/default-user/mode", json={"interaction_mode": "desk"}, headers=OWNER)
            private = upload(client, sid, 2, generation)  # calendar reply is work-private
            assert private.headers["x-voice-turn-outcome"] == "withheld"

            client.patch("/sessions/default-user/dnd", json={"dnd": True}, headers=OWNER)
            dnd = upload(client, sid, 3, generation)
            assert dnd.headers["x-voice-turn-outcome"] == "withheld"

            client.patch("/sessions/default-user/dnd", json={"dnd": False}, headers=OWNER)
            client.patch("/sessions/default-user/privacy-context", json={"privacy_context": "meeting"}, headers=OWNER)
            meeting = upload(client, sid, 4, generation)
            assert meeting.headers["x-voice-turn-outcome"] == "withheld"

            assert tts.spoken == []
            turns = wait_for_state(client, "listening")["turns"]
            assert [t["outcome"] for t in turns] == ["withheld"] * 4
            assert "phone" in turns[0]["reason"] and "Telegram is not available" in turns[0]["reason"]
            assert "web" in turns[1]["reason"]
            assert turns[2]["reason"] == "Do not disturb is on"
            assert turns[3]["reason"] == "You are marked as in a meeting"
            assert all(t["reply"] for t in turns)  # visible to the owner instead
            assert all(t["conversation_ms"] is not None and t["synthesis_ms"] is None for t in turns)
        finally:
            ws.__exit__(None, None, None)


def test_spoken_command_text_does_not_actuate_the_robot() -> None:
    # Even if STT produced the literal typed-command syntax, voice is not
    # an authenticated command channel (Phase 24b + ADR 0023).
    stt = ScriptedSTT("/reachy standby", "turn off reachy")
    tts = RecordingTTS()
    client, _, embodiment = make_hub(stt, tts)
    with client:
        ws, socket, generation = connect_robot(client)
        try:
            sid = start_listening(client, socket)
            upload(client, sid, 1, generation)
            socket.send_json({"type": "voice_state", "voice_session_id": sid, "state": "listening"})
            wait_for_state(client, "listening")
            upload(client, sid, 2, generation)
            # Both went to the ordinary conversation branch (core's
            # placeholder reply), not the command branch, which would have
            # tried to reach the hub's standby route.
            assert len(tts.spoken) == 2
            assert all("turn" in text and "reachy-hub" not in text for text in tts.spoken)
            assert embodiment.state.backend.connected is True
        finally:
            ws.__exit__(None, None, None)


def test_upload_authentication_bounds_and_validation() -> None:
    stt = ScriptedSTT("   ")
    client, _, _ = make_hub(stt, RecordingTTS())
    with client:
        ws, socket, generation = connect_robot(client)
        try:
            sid = start_listening(client, socket)
            assert upload(client, sid, 1, generation, token="wrong").status_code == 401
            assert upload(client, "other", 1, generation).status_code == 409
            assert upload(client, sid, 1, generation + 1).status_code == 409
            assert upload(client, sid, 1, generation, body=b"x" * (MAX_UTTERANCE_BYTES + 1)).status_code == 413
            assert stt.calls == 0

            bad = upload(client, sid, 1, generation, body=wav_bytes(rate=44100))
            assert bad.status_code == 422
            too_long = upload(client, sid, 2, generation, body=wav_bytes(seconds=17))
            assert too_long.status_code == 422
            assert stt.calls == 0

            silence = upload(client, sid, 3, generation)
            assert (silence.status_code, silence.headers["x-voice-turn-outcome"]) == (204, "no_speech")
            assert wait_for_state(client, "listening")["next_turn"] == 4
        finally:
            ws.__exit__(None, None, None)


def test_owner_controls_require_auth_and_logout_stops_listening() -> None:
    client, _, _ = make_hub(ScriptedSTT(), RecordingTTS())
    with client:
        ws, socket, _ = connect_robot(client)
        try:
            assert client.post("/robot-voice/start", json={"robot_id": ROBOT_ID}).status_code == 401
            assert client.get("/robot-voice").status_code == 401
            # The robot's own credential is not an owner credential.
            robot_bearer = {"Authorization": f"Bearer {ROBOT_TOKEN}"}
            assert client.post("/robot-voice/start", json={"robot_id": ROBOT_ID}, headers=robot_bearer).status_code == 401

            login = client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF)
            assert login.status_code == 200
            # Cookie auth needs the same-origin header for a state change.
            assert client.post("/robot-voice/start", json={"robot_id": ROBOT_ID}).status_code == 403
            started = client.post("/robot-voice/start", json={"robot_id": ROBOT_ID}, headers=CSRF)
            assert started.status_code == 200
            assert started.headers["cache-control"] == "no-store"
            sid = socket.receive_json()["voice_session_id"]

            client.post("/auth/logout", headers=CSRF)
            stop = socket.receive_json()
            assert stop == {"type": "voice_stop", "voice_session_id": sid, "reason": "Owner logged out"}
            status = client.get("/robot-voice", headers=OWNER).json()["session"]
            assert (status["state"], status["stop_reason"]) == ("stopped", "Owner logged out")
            assert upload(client, sid, 1, 1).status_code == 409
        finally:
            ws.__exit__(None, None, None)


def test_robot_without_voice_capability_cannot_be_started_and_disconnect_stops() -> None:
    client, _, _ = make_hub(ScriptedSTT(), RecordingTTS())
    with client:
        ws, _, _ = connect_robot(client, capabilities=())
        overview = client.get("/robot-voice", headers=OWNER).json()
        assert overview["robots"] == [{"robot_id": ROBOT_ID, "online": True, "voice_capable": False}]
        refused = client.post("/robot-voice/start", json={"robot_id": ROBOT_ID}, headers=OWNER)
        assert refused.status_code == 409
        ws.__exit__(None, None, None)

        ws, socket, _ = connect_robot(client)
        start_listening(client, socket)
        ws.__exit__(None, None, None)
        stopped = wait_for_state(client, "stopped")
        assert stopped["stop_reason"] == "Robot disconnected"


def test_robot_reported_stop_and_errors_are_visible() -> None:
    client, _, _ = make_hub(ScriptedSTT(), RecordingTTS())
    with client:
        ws, socket, _ = connect_robot(client)
        try:
            sid = start_listening(client, socket)
            socket.send_json({"type": "voice_state", "voice_session_id": sid, "state": "error", "detail": "Speaker playback failed"})
            deadline = time.monotonic() + 5
            while client.get("/robot-voice", headers=OWNER).json()["session"]["last_error"] is None:
                assert time.monotonic() < deadline
                time.sleep(0.02)
            socket.send_json({"type": "voice_state", "voice_session_id": sid, "state": "stopped", "detail": "Microphone unavailable"})
            assert wait_for_state(client, "stopped")["stop_reason"] == "Microphone unavailable"
        finally:
            ws.__exit__(None, None, None)


@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_real_speech_providers_through_the_robot_upload_route() -> None:
    from reachy_hub.stt import FasterWhisperSTT
    from reachy_hub.tts import EspeakTTS

    client, _, _ = make_hub(FasterWhisperSTT(model_size="tiny.en"), EspeakTTS())
    question = EspeakTTS().synthesize("remember that my favourite colour is green")
    with wave.open(io.BytesIO(question)) as source:
        rate, frames = source.getframerate(), source.readframes(source.getnframes())
    import numpy as np

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    target = np.interp(
        np.linspace(0, len(samples), int(len(samples) * 16000 / rate), endpoint=False),
        np.arange(len(samples)),
        samples,
    ).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(target.tobytes())

    with client:
        ws, socket, generation = connect_robot(client)
        try:
            sid = start_listening(client, socket)
            reply = upload(client, sid, 1, generation, body=buf.getvalue())
            assert reply.status_code == 200
            with wave.open(io.BytesIO(reply.content)) as spoken:
                assert spoken.getnframes() > 0
            turn = client.get("/robot-voice", headers=OWNER).json()["session"]["turns"][0]
            assert "green" in turn["transcript"].lower()
        finally:
            ws.__exit__(None, None, None)


def test_first_use_model_loading_does_not_block_the_event_loop() -> None:
    """Found in the Phase 24c Compose run: constructing the STT provider
    (a model download on first use) on the event loop stalled the robot's
    WSS keepalive until it disconnected. It must happen in a worker thread."""

    def slow_factory():
        time.sleep(1.5)
        return ScriptedSTT("")

    app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False,
        run_telegram_poll_task=False,
        run_voice_watchdog_task=False,
        stt_factory=slow_factory,
    )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as client:
            turn = asyncio.create_task(
                client.post("/voice/turn", data={"user_id": "u"}, files={"audio": ("a.wav", wav_bytes(), "audio/wav")})
            )
            # Timed from before yielding: a blocked loop delays the sleep's
            # own wake-up, not just the request after it.
            started = time.monotonic()
            await asyncio.sleep(0.2)
            assert (await client.get("/health")).status_code == 200
            responsive_in = time.monotonic() - started
            assert (await turn).status_code == 422  # empty transcript
            return responsive_in

    assert asyncio.run(scenario()) < 0.8


def test_legacy_voice_turn_requires_the_owner_before_any_transcription() -> None:
    """/voice/turn has no route dependency of its own; the owner-bound
    private_work_routes middleware gates it (a production hub cannot start
    without ACCOUNTS_SERVICE_TOKEN). Proves anonymous, wrong-user and
    cookie-without-CSRF calls are refused before STT ever runs."""
    stt = ScriptedSTT("hello")
    client, _, _ = make_hub(stt, RecordingTTS(), accounts_service_token="svc-token")
    audio = {"audio": ("q.wav", wav_bytes(), "audio/wav")}
    with client:
        assert client.post("/voice/turn", data={"user_id": "default-user"}, files=audio).status_code == 401
        robot_bearer = {"Authorization": f"Bearer {ROBOT_TOKEN}"}
        assert client.post("/voice/turn", data={"user_id": "default-user"}, files=audio, headers=robot_bearer).status_code == 401
        other_user = client.post("/voice/turn", data={"user_id": "someone-else"}, files=audio, headers=OWNER)
        assert other_user.status_code == 403
        client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF)
        assert client.post("/voice/turn", data={"user_id": "default-user"}, files=audio).status_code == 403
        assert stt.calls == 0

        allowed = client.post("/voice/turn", data={"user_id": "default-user"}, files=audio, headers=OWNER)
        assert allowed.status_code == 200
        assert stt.calls == 1
