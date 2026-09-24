"""Phase 24c robot-side conversation loop (ADR 0023).

Segmenter and mic-source tests are pure/controlled-time. The chain tests
run the robot's real VoiceConversation against the real reachy-hub app
(robot upload over httpx.ASGITransport) and real companion-core, with the
control socket bridged in process; one test uses real sockets (uvicorn hub
+ the actual `websockets` robot client). The simulated microphone plays
synthetic fixtures; real speech is exercised in the `slow` test. None of
this is the physical robot.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import shutil
import socket
import time
import wave

import httpx
import numpy as np
import pytest
import uvicorn
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
from reachy_embodiment.audio.vad import CHUNK_SAMPLES
from reachy_embodiment.robot import (
    ReachyDaemonBackend,
    ReachyMiniMicSource,
    SimulatedMicSource,
    SimulatedRobotBackend,
    wav_duration,
)
from reachy_embodiment.robot_ws_client import RobotWSClient
from reachy_embodiment.state import ServiceState
from reachy_embodiment.voice import (
    UtteranceSegmenter,
    VoiceConversation,
    VoiceTurnClient,
    encode_wav,
)
from reachy_hub.app import create_app as create_hub_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_credential_store import InMemoryRobotCredentialStore
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.robot_voice import RobotVoiceManager
from reachy_hub.session_store import InMemorySessionStore

from shared.models.embodiment import EmbodimentState
from shared.models.robot_voice import VOICE_CAPABILITY, VoiceLimits
from shared.models.robot_ws import VoiceStartMessage, VoiceStateMessage, WSMessageType

SR = 16000
ROBOT_ID = "nano-1"
ROBOT_TOKEN = "robot-secret"
OWNER = {"Authorization": "Bearer owner-token"}
espeak_binary = shutil.which("espeak-ng")


class EnergyVAD:
    """Deterministic stand-in for Silero: loud chunk starts speech, five
    quiet chunks (160 ms) end it. Real Silero is tested separately."""

    def __init__(self, quiet_chunks_to_end: int = 5) -> None:
        self.quiet_needed = quiet_chunks_to_end
        self.reset()

    def reset(self) -> None:
        self.speaking = False
        self.quiet = 0

    def process_chunk(self, chunk: np.ndarray) -> dict | None:
        loud = float(np.sqrt(np.mean(chunk**2))) > 0.05
        if not self.speaking:
            if loud:
                self.speaking, self.quiet = True, 0
                return {"start": 0}
            return None
        self.quiet = 0 if loud else self.quiet + 1
        if self.quiet >= self.quiet_needed:
            self.reset()
            return {"end": 0}
        return None


def tone(seconds: float, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype=np.float32)


# --- segmentation and sources --------------------------------------------


def test_segmenter_includes_preroll_and_ends_on_silence() -> None:
    limits = VoiceLimits(pre_roll_ms=128, min_utterance_ms=100)
    segmenter = UtteranceSegmenter(EnergyVAD(), limits)
    assert segmenter.feed(silence(1.0)) is None
    # Arrives in arbitrary-sized pieces, as the SDK delivers it.
    stream = np.concatenate([tone(0.5), silence(0.5)])
    utterance = None
    for piece in np.array_split(stream, 7):
        utterance = utterance if utterance is not None else segmenter.feed(piece)
    assert utterance is not None
    preroll_chunks = 4  # 128 ms of 32 ms chunks
    speech_chunks = int(np.ceil(0.5 * SR / CHUNK_SAMPLES))
    assert len(utterance) >= (preroll_chunks + speech_chunks) * CHUNK_SAMPLES - CHUNK_SAMPLES
    assert np.all(utterance[: 3 * CHUNK_SAMPLES] == 0)  # the pre-roll is silence here


def test_segmenter_drops_clicks_and_cuts_at_the_maximum_length() -> None:
    segmenter = UtteranceSegmenter(EnergyVAD(), VoiceLimits(min_utterance_ms=300, pre_roll_ms=0))
    assert segmenter.feed(np.concatenate([tone(0.03), silence(0.5)])) is None  # a click

    segmenter = UtteranceSegmenter(EnergyVAD(), VoiceLimits(max_utterance_seconds=1.0, pre_roll_ms=0))
    utterance = segmenter.feed(tone(3.0))  # nobody stops talking
    assert utterance is not None
    assert len(utterance) <= int(np.ceil(1.0 * SR / CHUNK_SAMPLES)) * CHUNK_SAMPLES


def test_encode_wav_is_16k_mono_16bit() -> None:
    with wave.open(io.BytesIO(encode_wav(tone(0.25)))) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (SR, 1, 2)
        assert wav.getnframes() == int(0.25 * SR)


def test_wav_duration_ignores_a_streaming_placeholder_header() -> None:
    # espeak-ng --stdout writes 0x7fffffff as the data size before it knows
    # the length; trusting it made the robot wait ~13 hours per reply.
    proper = encode_wav(tone(1.5))
    streamed = bytearray(proper)
    streamed[4:8] = (0x7FFFFFFF).to_bytes(4, "little")
    streamed[40:44] = (0x7FFFFFFF - 36).to_bytes(4, "little")
    assert wav_duration(bytes(streamed)) == pytest.approx(1.5)
    assert SimulatedRobotBackend().play_audio(bytes(streamed)) == pytest.approx(1.5)


def test_simulated_mic_paces_in_real_time_and_serves_one_fixture_per_listen() -> None:
    now = [0.0]
    mic = SimulatedMicSource([tone(0.5), tone(0.2)], clock=lambda: now[0])
    assert mic.read() is None  # not started
    mic.start()
    now[0] = 0.1
    first = mic.read()
    assert len(first) == int(0.1 * SR) and not first.any()  # lead-in silence
    now[0] = 1.0
    rest = mic.read()
    assert np.allclose(rest[int(0.2 * SR) : int(0.7 * SR)], tone(0.5))
    mic.stop()
    assert mic.read() is None
    mic.start()
    now[0] = 2.0
    assert np.abs(mic.read()).max() > 0.1  # second fixture
    mic.stop()
    mic.start()
    now[0] = 3.0
    assert not mic.read().any()  # queue exhausted: silence


def test_reachy_mini_mic_source_downmixes_sdk_stereo() -> None:
    class Media:
        def __init__(self):
            self.calls: list[str] = []

        def start_recording(self):
            self.calls.append("start")

        def stop_recording(self):
            self.calls.append("stop")

        def get_audio_sample(self):
            return np.array([[0.2, 0.4], [0.0, -0.2]], dtype=np.float32)

    media = Media()
    source = ReachyMiniMicSource(media)
    source.start()
    assert np.allclose(source.read(), [0.3, -0.1])
    source.stop()
    assert media.calls == ["start", "stop"]


def test_daemon_backend_stop_audio_and_verified_upload_shape() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/media/sounds/upload"):
            return httpx.Response(200, json={"status": "ok", "path": "/tmp/reachy_mini_sounds/x.wav"})
        return httpx.Response(200, json={"status": "ok"})

    backend = ReachyDaemonBackend("http://daemon.test", transport=httpx.MockTransport(handler))
    assert backend.play_audio(encode_wav(tone(0.5))) == pytest.approx(0.5)
    backend.stop_audio()
    assert requests == [
        ("POST", "/api/media/sounds/upload"),
        ("POST", "/api/media/play_sound"),
        ("POST", "/api/media/stop_sound"),
    ]


# --- robot <-> hub <-> core chain, in process ----------------------------


class RecordingPlayer:
    def __init__(self) -> None:
        self.played: list[float] = []
        self.stopped = 0
        self.play_started = asyncio.Event()

    def play_audio(self, wav_bytes: bytes) -> float:
        with wave.open(io.BytesIO(wav_bytes)) as wav:
            duration = wav.getnframes() / wav.getframerate()
        self.played.append(duration)
        return duration

    def stop_audio(self) -> None:
        self.stopped += 1


class CountingMic(SimulatedMicSource):
    def __init__(self, utterances, *, fail: bool = False):
        # 20x real time keeps the chain tests quick without sleeping less
        # accurately than the code under test expects.
        super().__init__(utterances, clock=lambda: time.monotonic() * 20)
        self.starts = 0
        self.fail = fail

    def start(self) -> None:
        if self.fail:
            raise OSError("device busy")
        self.starts += 1
        super().start()


class ScriptedSTT:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)

    def transcribe(self, wav: bytes) -> str:
        return self.texts.pop(0) if self.texts else ""


class FixedTTS:
    def __init__(self, seconds: float = 0.1) -> None:
        self.seconds = seconds
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.spoken.append(text)
        return encode_wav(silence(self.seconds))


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


def make_hub(stt, tts, *, limits: VoiceLimits | None = None):
    from reachy_hub.robot_connection_manager import RobotConnectionManager

    credentials = InMemoryRobotCredentialStore()
    credentials.provision(ROBOT_ID, ROBOT_TOKEN)
    connections = RobotConnectionManager()
    limits = limits or VoiceLimits(playback_tail_guard_ms=0)
    app = create_hub_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=create_core_app())),
        run_heartbeat_task=False,
        run_telegram_poll_task=False,
        run_voice_watchdog_task=False,
        robot_credential_store=credentials,
        robot_connection_manager=connections,
        robot_voice_manager=RobotVoiceManager(connections, limits=limits),
        remote_ui_token="owner-token",
        stt=stt,
        tts=tts,
    )
    return app


class Robot:
    """The robot's VoiceConversation, with the ADR 0019 control socket
    replaced by an in-process bridge into the hub's connection manager."""

    def __init__(self, hub_app, mic, player, *, hub_transport=None):
        self.hub_app = hub_app
        self.mic = mic
        self.player = player
        self.state = ServiceState(connected=True, sim=True)
        self.voice = VoiceConversation(
            lambda: mic,
            lambda limits: EnergyVAD(),
            VoiceTurnClient("http://hub", ROBOT_ID, ROBOT_TOKEN, transport=hub_transport or httpx.ASGITransport(app=hub_app)),
            player,
            self.state,
        )
        self.reports: list[str] = []
        self.connection = None

    async def connect(self):
        manager = self.hub_app.state.robot_connection_manager
        self.connection = await manager.register(ROBOT_ID, self, capabilities=[VOICE_CAPABILITY], sim=True)

    async def send_json(self, message: dict) -> None:  # hub -> robot
        if message["type"] == WSMessageType.VOICE_START:
            await self.voice.start(VoiceStartMessage.model_validate(message), self.connection.generation, self.report)
        elif message["type"] == WSMessageType.VOICE_STOP:
            await self.voice.stop(message["voice_session_id"])

    async def close(self, code: int = 1000) -> None:
        pass

    async def report(self, message: VoiceStateMessage) -> None:  # robot -> hub
        self.reports.append(message.state.value)
        await self.hub_app.state.robot_voice_manager.on_robot_message(self.connection, message.model_dump(mode="json"))


async def owner(hub_app, method, path, **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hub_app), base_url="http://hub") as client:
        return await client.request(method, path, headers=OWNER, **kwargs)


async def wait_until(predicate, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


def utterance_fixture() -> np.ndarray:
    return np.concatenate([tone(0.6), silence(0.3)])


def test_multi_turn_conversation_through_hub_and_core() -> None:
    async def scenario():
        tts = FixedTTS()
        hub = make_hub(ScriptedSTT("hello reachy", "what did I say"), tts)
        mic = CountingMic([utterance_fixture(), utterance_fixture()])
        player = RecordingPlayer()
        robot = Robot(hub, mic, player)
        await robot.connect()
        assert (await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})).status_code == 200

        await wait_until(lambda: len(player.played) == 2 and robot.reports.count("listening") >= 3)
        session = (await owner(hub, "GET", "/robot-voice")).json()["session"]
        assert [t["transcript"] for t in session["turns"]] == ["hello reachy", "what did I say"]
        assert [t["outcome"] for t in session["turns"]] == ["spoken", "spoken"]
        assert "turn 2" in tts.spoken[1]  # one conversation across turns
        assert session["state"] == "listening"
        # Half-duplex: the robot reported each phase in order.
        assert robot.reports[:4] == ["listening", "uploading", "speaking", "listening"]
        assert robot.state.embodiment_state == EmbodimentState.LISTENING

        await owner(hub, "POST", "/robot-voice/stop", json={"voice_session_id": session["voice_session_id"]})
        await wait_until(lambda: robot.state.embodiment_state == EmbodimentState.IDLE)
        starts = mic.starts
        await asyncio.sleep(0.3)
        assert mic.starts == starts  # nothing restarts capture by itself
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_stop_during_playback_silences_the_speaker() -> None:
    async def scenario():
        hub = make_hub(ScriptedSTT("tell me a long story"), FixedTTS(seconds=30))
        player = RecordingPlayer()
        robot = Robot(hub, CountingMic([utterance_fixture()]), player)
        await robot.connect()
        start = (await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})).json()
        await wait_until(lambda: player.played)
        assert robot.state.embodiment_state == EmbodimentState.SPEAKING

        stopped_at = time.monotonic()
        await owner(hub, "POST", "/robot-voice/stop", json={"voice_session_id": start["voice_session_id"]})
        assert player.stopped == 1
        assert time.monotonic() - stopped_at < 1.0
        assert robot.state.embodiment_state == EmbodimentState.IDLE
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_withheld_reply_is_not_played_and_listening_resumes() -> None:
    async def scenario():
        hub = make_hub(ScriptedSTT("what is on my calendar", "hello"), FixedTTS())
        player = RecordingPlayer()
        robot = Robot(hub, CountingMic([utterance_fixture(), utterance_fixture()]), player)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: len(player.played) == 1)
        turns = (await owner(hub, "GET", "/robot-voice")).json()["session"]["turns"]
        assert [t["outcome"] for t in turns] == ["withheld", "spoken"]
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_hub_failure_is_reported_and_the_next_turn_still_works() -> None:
    class FlakySTT(ScriptedSTT):
        def transcribe(self, wav):
            if not hasattr(self, "failed"):
                self.failed = True
                raise RuntimeError("model crashed")
            return super().transcribe(wav)

    async def scenario():
        hub = make_hub(FlakySTT("second try"), FixedTTS())
        player = RecordingPlayer()
        robot = Robot(hub, CountingMic([utterance_fixture(), utterance_fixture()]), player)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: len(player.played) == 1)
        session = (await owner(hub, "GET", "/robot-voice")).json()["session"]
        assert [t["outcome"] for t in session["turns"]] == ["failed", "spoken"]
        assert session["last_error"] == "Speech recognition failed"
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_microphone_failure_and_robot_side_session_limit_end_the_hub_session() -> None:
    async def scenario():
        hub = make_hub(ScriptedSTT(), FixedTTS())
        robot = Robot(hub, CountingMic([], fail=True), RecordingPlayer())
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: "stopped" in robot.reports)
        session = (await owner(hub, "GET", "/robot-voice")).json()["session"]
        assert (session["state"], session["stop_reason"]) == ("stopped", "Microphone unavailable")

        hub = make_hub(ScriptedSTT(), FixedTTS(), limits=VoiceLimits(max_session_seconds=0.3))
        robot = Robot(hub, CountingMic([]), RecordingPlayer())
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: "stopped" in robot.reports)
        session = (await owner(hub, "GET", "/robot-voice")).json()["session"]
        assert session["stop_reason"] == "Maximum conversation length reached"

    asyncio.run(scenario())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_websocket_control_and_http_upload_against_a_running_hub() -> None:
    """Real sockets: uvicorn serves the hub; the robot's actual
    RobotWSClient registers over WS, receives voice_start, uploads over
    HTTP, and a dropped connection stops capture with no restart."""

    async def scenario():
        hub = make_hub(ScriptedSTT("hello over the network"), FixedTTS())
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(hub, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
        serve = asyncio.create_task(server.serve())
        await wait_until(lambda: server.started)
        url = f"http://127.0.0.1:{port}"

        player = RecordingPlayer()
        mic = CountingMic([utterance_fixture()])
        state = ServiceState(connected=True, sim=True)
        voice = VoiceConversation(lambda: mic, lambda limits: EnergyVAD(), VoiceTurnClient(url, ROBOT_ID, ROBOT_TOKEN), player, state)
        client = RobotWSClient(url, ROBOT_ID, ROBOT_TOKEN, sim=True, voice=voice)
        run = asyncio.create_task(client.run())
        try:
            await wait_until(lambda: client.connected)
            async with httpx.AsyncClient(base_url=url, headers=OWNER) as owner_client:
                overview = (await owner_client.get("/robot-voice")).json()
                assert overview["robots"] == [{"robot_id": ROBOT_ID, "online": True, "voice_capable": True}]
                assert (await owner_client.post("/robot-voice/start", json={"robot_id": ROBOT_ID})).status_code == 200
                await wait_until(lambda: player.played)
                await wait_until(lambda: state.embodiment_state == EmbodimentState.LISTENING)

                # Hub restarts/network drops: the robot's socket closes.
                server.should_exit = True
                await serve
                await wait_until(lambda: not client.connected)
                await wait_until(lambda: state.embodiment_state == EmbodimentState.IDLE)
                starts = mic.starts
                await asyncio.sleep(0.3)
                assert mic.starts == starts
        finally:
            run.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run
            server.should_exit = True
            with contextlib.suppress(Exception):
                await serve
            await voice.aclose()

    asyncio.run(scenario())


# --- real speech ---------------------------------------------------------


def _espeak_16k(text: str) -> np.ndarray:
    import subprocess

    raw = subprocess.run([espeak_binary, "-v", "en-us", "--stdout", text], capture_output=True, check=True).stdout
    with wave.open(io.BytesIO(raw)) as wav:
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    target = int(len(samples) * SR / rate)
    return np.interp(np.linspace(0, len(samples), target, endpoint=False), np.arange(len(samples)), samples).astype(
        np.float32
    )


@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_real_silero_vad_segments_one_spoken_utterance() -> None:
    from reachy_embodiment.audio.vad import VoiceActivityDetector

    limits = VoiceLimits()
    segmenter = UtteranceSegmenter(
        VoiceActivityDetector(min_silence_duration_ms=limits.end_of_speech_silence_ms), limits
    )
    speech = _espeak_16k("please remind me to call the dentist tomorrow")
    stream = np.concatenate([silence(1.0), speech, silence(1.5)])
    utterance = None
    for piece in np.array_split(stream, 40):
        if utterance is None:
            utterance = segmenter.feed(piece)
    assert utterance is not None
    assert len(speech) * 0.8 < len(utterance) < len(speech) + 1.5 * SR


@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_real_speech_chain_with_silero_whisper_and_espeak() -> None:
    from reachy_embodiment.audio.vad import VoiceActivityDetector
    from reachy_hub.stt import FasterWhisperSTT
    from reachy_hub.tts import EspeakTTS

    async def scenario():
        tts = EspeakTTS()
        hub = make_hub(FasterWhisperSTT(model_size="tiny.en"), tts)
        player = RecordingPlayer()
        mic = SimulatedMicSource([_espeak_16k("my favourite colour is green"), _espeak_16k("what is my favourite colour")])
        robot = Robot(hub, mic, player)
        robot.voice._vad_factory = lambda limits: VoiceActivityDetector(
            min_silence_duration_ms=limits.end_of_speech_silence_ms
        )
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: len(player.played) == 2, timeout=120)
        turns = (await owner(hub, "GET", "/robot-voice")).json()["session"]["turns"]
        assert "green" in turns[0]["transcript"].lower()
        assert "colour" in turns[1]["transcript"].lower() or "color" in turns[1]["transcript"].lower()
        assert all(duration > 0.3 for duration in player.played)
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_simulated_backend_exposes_a_microphone_and_stop() -> None:
    backend = SimulatedRobotBackend()
    assert isinstance(backend.open_microphone(), SimulatedMicSource)
    backend.stop_audio()
