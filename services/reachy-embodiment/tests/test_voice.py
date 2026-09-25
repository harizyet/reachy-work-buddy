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
from reachy_embodiment.gesture import HubPalmStop
from reachy_embodiment.motion import MotionController
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
from reachy_hub.palm_stop import PalmStop
from reachy_hub.robot_credential_store import InMemoryRobotCredentialStore
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.robot_voice import RobotVoiceManager
from reachy_hub.session_store import InMemorySessionStore

from shared.models.embodiment import Behaviour, EmbodimentState
from shared.models.robot_voice import (
    PALM_FRAME_MAX_WIDTH,
    VOICE_CAPABILITY,
    VOICE_CONTINUATION_CAPABILITY,
    VoiceLimits,
    VoiceTurnOutcome,
)
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

    def transcribe(self, wav: bytes, *, vocabulary: tuple[str, ...] = ()) -> str:
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


def make_hub(stt, tts, *, limits: VoiceLimits | None = None, palm_detector=None):
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
        robot_voice_manager=RobotVoiceManager(
            connections,
            limits=limits,
            palm_stop=PalmStop(lambda: palm_detector) if palm_detector is not None else None,
        ),
        remote_ui_token="owner-token",
        stt=stt,
        tts=tts,
    )
    return app


class Robot:
    """The robot's VoiceConversation, with the ADR 0019 control socket
    replaced by an in-process bridge into the hub's connection manager."""

    def __init__(
        self,
        hub_app,
        mic,
        player,
        *,
        hub_transport=None,
        capabilities=(VOICE_CAPABILITY,),
        stop_gesture=None,
        motion_backend=None,
    ):
        self.hub_app = hub_app
        self.capabilities = list(capabilities)
        self.mic = mic
        self.player = player
        self.state = ServiceState(connected=True, sim=True)
        self.motion = None
        if motion_backend is not None:
            self.motion = MotionController(
                motion_backend, self.state, conversation_motion=True, speech_wobble=True, home_settle_seconds=0.0
            )
        self.voice = VoiceConversation(
            lambda: mic,
            lambda limits: EnergyVAD(),
            VoiceTurnClient("http://hub", ROBOT_ID, ROBOT_TOKEN, transport=hub_transport or httpx.ASGITransport(app=hub_app)),
            player,
            self.state,
            stop_gesture=stop_gesture,
            motion=self.motion,
        )
        self.reports: list[str] = []
        self.connection = None

    async def connect(self):
        manager = self.hub_app.state.robot_connection_manager
        self.connection = await manager.register(ROBOT_ID, self, capabilities=self.capabilities, sim=True)

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


class FakePalm:
    """Stands in for the robot's HubPalmStop: `show()` makes a waiting
    `wait()` return, as the hub's stop answer would."""

    def __init__(self, *, ready: bool = True, fail: bool = False) -> None:
        self.ready = ready
        self.fail = fail
        self.prepared = 0
        self.waits = 0
        self.cancelled = 0
        self.closed = 0
        self._shown = asyncio.Event()

    def show(self) -> None:
        self._shown.set()

    async def prepare(self) -> bool:
        self.prepared += 1
        return self.ready

    async def wait(self, voice_session_id: str, turn: int, generation: int) -> None:
        self.waits += 1
        self.context = (voice_session_id, turn, generation)
        if self.fail:
            raise RuntimeError("camera gone")
        try:
            await self._shown.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        self._shown.clear()

    def close(self) -> None:
        self.closed += 1


def test_open_palm_stops_a_long_reply_and_listening_resumes() -> None:
    async def scenario():
        tts = FixedTTS(seconds=30)
        hub = make_hub(ScriptedSTT("tell me a long story", "thanks"), tts, palm_detector=NoPalm())
        mic = CountingMic([utterance_fixture(), utterance_fixture()])
        player = RecordingPlayer()
        palm = FakePalm()
        robot = Robot(hub, mic, player, stop_gesture=palm)
        await robot.connect()
        start = (await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})).json()
        await wait_until(lambda: player.played)
        assert robot.state.embodiment_state == EmbodimentState.SPEAKING
        assert palm.prepared == 1 and palm.waits == 1
        assert palm.context == (start["voice_session_id"], 1, robot.connection.generation)

        shown_at = time.monotonic()
        palm.show()
        await wait_until(lambda: player.stopped == 1)
        assert time.monotonic() - shown_at < 1.0
        # Same session carries on: the robot listens and answers the next turn.
        await wait_until(lambda: len(player.played) == 2)
        session = (await owner(hub, "GET", "/robot-voice")).json()["session"]
        assert session["voice_session_id"] == start["voice_session_id"]
        assert [t["transcript"] for t in session["turns"]] == ["tell me a long story", "thanks"]
        assert robot.reports[:5] == ["listening", "uploading", "speaking", "listening", "uploading"]
        assert palm.prepared == 1  # the detector is set up once per session, not per reply

        await owner(hub, "POST", "/robot-voice/stop", json={"voice_session_id": start["voice_session_id"]})
        assert player.stopped == 2  # the second reply was still playing
        assert palm.cancelled == 1  # its watcher ended with the playback
        await robot.voice.aclose()
        assert palm.closed == 1

    asyncio.run(scenario())


class NoPalm:
    """Hub-side detector that never sees a palm; enables palm stop."""

    def is_open_palm(self, jpeg: bytes) -> bool:
        return False

    def close(self) -> None:
        pass


class ShownPalm:
    """Hub-side detector: an open palm once `show()` is called."""

    def __init__(self) -> None:
        self.shown = False
        self.frames = 0

    def is_open_palm(self, jpeg: bytes) -> bool:
        self.frames += 1
        return self.shown and jpeg.startswith(b"\xff\xd8")

    def close(self) -> None:
        pass


def test_open_palm_over_the_real_frame_upload_stops_the_reply() -> None:
    """Robot HubPalmStop -> hub ROBOT_PALM_FRAME -> hub PalmStop, in process."""

    async def scenario():
        detector = ShownPalm()
        hub = make_hub(ScriptedSTT("tell me a long story", "thanks"), FixedTTS(seconds=30), palm_detector=detector)
        player = RecordingPlayer()
        backend = SimulatedRobotBackend()
        uploader = VoiceTurnClient("http://hub", ROBOT_ID, ROBOT_TOKEN, transport=httpx.ASGITransport(app=hub))
        palm = HubPalmStop(lambda: backend.capture_frame(max_width=PALM_FRAME_MAX_WIDTH), uploader.palm_frame, interval=0.05)
        robot = Robot(hub, CountingMic([utterance_fixture(), utterance_fixture()]), player, stop_gesture=palm)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: player.played and detector.frames >= 2)
        assert player.stopped == 0  # frames flow, no palm yet

        shown_at = time.monotonic()
        detector.shown = True
        await wait_until(lambda: player.stopped == 1)
        assert time.monotonic() - shown_at < 1.0
        await wait_until(lambda: len(player.played) == 2)  # same session, next turn answered
        session = (await owner(hub, "GET", "/robot-voice")).json()["session"]
        assert session["turns"][0]["reason"] == "Stopped by an open palm"
        await robot.voice.aclose()
        await uploader.aclose()

    asyncio.run(scenario())


def test_robot_does_not_watch_when_the_hub_has_palm_stop_off() -> None:
    async def scenario():
        hub = make_hub(ScriptedSTT("hello"), FixedTTS(seconds=0.2))
        player = RecordingPlayer()
        palm = FakePalm()
        robot = Robot(hub, CountingMic([utterance_fixture()]), player, stop_gesture=palm)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: player.played)
        await wait_until(lambda: robot.state.embodiment_state == EmbodimentState.LISTENING)
        assert (palm.prepared, palm.waits) == (0, 0)  # camera never read
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_reply_that_ends_normally_cancels_the_palm_watcher() -> None:
    async def scenario():
        hub = make_hub(ScriptedSTT("hello"), FixedTTS(seconds=0.1), palm_detector=NoPalm())
        player = RecordingPlayer()
        palm = FakePalm()
        robot = Robot(hub, CountingMic([utterance_fixture()]), player, stop_gesture=palm)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: palm.cancelled == 1)
        assert player.stopped == 0
        await wait_until(lambda: robot.state.embodiment_state == EmbodimentState.LISTENING)
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_palm_stop_unavailable_or_failing_leaves_replies_playing() -> None:
    async def scenario(palm: FakePalm):
        hub = make_hub(ScriptedSTT("hello"), FixedTTS(seconds=0.5), palm_detector=NoPalm())
        player = RecordingPlayer()
        robot = Robot(hub, CountingMic([utterance_fixture()]), player, stop_gesture=palm)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: player.played)
        started = time.monotonic()
        await wait_until(lambda: robot.state.embodiment_state == EmbodimentState.LISTENING)
        assert time.monotonic() - started >= 0.5  # played to its end
        assert player.stopped == 0
        await robot.voice.aclose()

    unavailable = FakePalm(ready=False)
    asyncio.run(scenario(unavailable))
    assert unavailable.waits == 0

    failing = FakePalm(fail=True)
    asyncio.run(scenario(failing))
    assert failing.waits == 1


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
        def transcribe(self, wav, *, vocabulary=()):
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


# --- adaptive end of turn (Phase 24e) --------------------------------------


class PushMic:
    """A microphone the test feeds by hand; `read` drains what was pushed."""

    def __init__(self) -> None:
        self.pending: list[np.ndarray] = []
        self.open = False
        self.starts = 0

    def push(self, samples: np.ndarray) -> None:
        self.pending.append(samples)

    def start(self) -> None:
        self.open, self.starts = True, self.starts + 1

    def read(self) -> np.ndarray | None:
        if not self.open or not self.pending:
            return None
        samples, self.pending = np.concatenate(self.pending), []
        return samples

    def stop(self) -> None:
        self.open = False
        self.pending = []


class ScriptedUploader:
    """Stands in for VoiceTurnClient: answers each upload or finalize from
    a script and records the calls."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple] = []

    async def post(self, wav, *, voice_session_id, turn, generation, segment=1):
        self.calls.append(("post", turn, segment))
        return self.outcomes.pop(0), None

    async def finalize(self, *, voice_session_id, turn, generation):
        self.calls.append(("finalize", turn))
        return self.outcomes.pop(0), None

    async def aclose(self) -> None:
        pass


def test_continuation_window_under_a_controlled_clock() -> None:
    """The window is timed from the segment cut on the injected clock; speech
    that starts inside it runs to its own end even past the window."""
    async def scenario():
        now = [100.0]
        mic = PushMic()
        uploader = ScriptedUploader(VoiceTurnOutcome.CONTINUE, VoiceTurnOutcome.CONTINUE, VoiceTurnOutcome.WITHHELD)
        voice = VoiceConversation(
            lambda: mic, lambda limits: EnergyVAD(), uploader, RecordingPlayer(), ServiceState(connected=True, sim=True),
            poll_interval=0.001, clock=lambda: now[0],
        )
        limits = VoiceLimits(continuation_window_ms=1500, pre_roll_ms=0, playback_tail_guard_ms=0)
        reports: list[str] = []

        async def report(message):
            reports.append(message.state.value)

        await voice.start(VoiceStartMessage(voice_session_id="s", limits=limits), 1, report)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([tone(0.5), silence(0.3)]))
        await wait_until(lambda: len(uploader.calls) == 1)
        assert uploader.calls == [("post", 1, 1)]
        await wait_until(lambda: reports.count("listening") == 2)  # resumed after continue, mic still open
        assert mic.starts == 1 and mic.open

        now[0] += 1.4  # inside the window: keep waiting
        await asyncio.sleep(0.05)
        assert len(uploader.calls) == 1
        mic.push(tone(0.3))  # speech starts again in time...
        await asyncio.sleep(0.05)
        now[0] += 5.0  # ...and runs well past the window
        await asyncio.sleep(0.05)
        assert len(uploader.calls) == 1
        mic.push(silence(0.3))
        await wait_until(lambda: len(uploader.calls) == 2)
        assert uploader.calls[1] == ("post", 1, 2)  # same turn, next segment

        await wait_until(lambda: reports.count("listening") == 3)
        now[0] += 1.4
        await asyncio.sleep(0.05)
        assert len(uploader.calls) == 2
        now[0] += 0.2  # window elapsed with no new speech
        await wait_until(lambda: len(uploader.calls) == 3)
        assert uploader.calls[2] == ("finalize", 1)
        # The turn ended: the microphone was closed, and the next turn has
        # the next number.
        await wait_until(lambda: mic.starts == 2)
        mic.push(np.concatenate([tone(0.5), silence(0.3)]))
        uploader.outcomes.append(VoiceTurnOutcome.WITHHELD)
        await wait_until(lambda: len(uploader.calls) == 4)
        assert uploader.calls[3] == ("post", 2, 1)
        await voice.aclose()
        assert not mic.open

    asyncio.run(scenario())


def test_a_final_outcome_discards_audio_captured_during_the_upload() -> None:
    async def scenario():
        mic = PushMic()
        released = asyncio.Event()

        class SlowUploader(ScriptedUploader):
            async def post(self, wav, **kwargs):
                mic.push(tone(0.4))  # speech arrives while the hub thinks
                await released.wait()
                return await super().post(wav, **kwargs)

        uploader = SlowUploader(VoiceTurnOutcome.WITHHELD, VoiceTurnOutcome.WITHHELD)
        voice = VoiceConversation(
            lambda: mic, lambda limits: EnergyVAD(), uploader, RecordingPlayer(), ServiceState(connected=True, sim=True),
            poll_interval=0.001,
        )
        limits = VoiceLimits(pre_roll_ms=0, playback_tail_guard_ms=0)
        await voice.start(VoiceStartMessage(voice_session_id="s", limits=limits), 1, _ignore_report)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([tone(0.5), silence(0.3)]))
        await asyncio.sleep(0.05)
        released.set()
        await wait_until(lambda: mic.starts == 2)
        await asyncio.sleep(0.05)
        # The speech heard during the upload did not become a turn.
        assert uploader.calls == [("post", 1, 1)]
        await voice.aclose()

    asyncio.run(scenario())


async def _ignore_report(message) -> None:
    pass


CONTINUATION = [VOICE_CAPABILITY, VOICE_CONTINUATION_CAPABILITY]


def paused_utterance() -> np.ndarray:
    # 20x mic time: the 0.4 s pause is ~20 ms of wall time, well inside the
    # window, but longer than the VAD's end of speech, so it is two segments.
    return np.concatenate([tone(0.6), silence(0.4), tone(0.6), silence(0.3)])


def test_long_utterance_with_a_pause_is_one_turn_through_hub_and_core() -> None:
    async def scenario():
        tts = FixedTTS()
        stt = ScriptedSTT("I was wondering if you could tell me.", "what the weather is like tomorrow.")
        hub = make_hub(stt, tts)
        player = RecordingPlayer()
        robot = Robot(hub, CountingMic([paused_utterance()]), player, capabilities=CONTINUATION)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: len(player.played) == 1)
        turns = (await owner(hub, "GET", "/robot-voice")).json()["session"]["turns"]
        assert [(t["turn"], t["segments"], t["outcome"]) for t in turns] == [(1, 2, "spoken")]
        assert turns[0]["transcript"] == "I was wondering if you could tell me. what the weather is like tomorrow."
        assert len(tts.spoken) == 1 and "turn 1" in tts.spoken[0]  # core saw one turn
        assert robot.reports[:5] == ["listening", "uploading", "listening", "uploading", "speaking"]
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_trailing_off_is_answered_after_the_window() -> None:
    async def scenario():
        tts = FixedTTS()
        hub = make_hub(
            ScriptedSTT("So I went to the"), tts, limits=VoiceLimits(playback_tail_guard_ms=0, continuation_window_ms=300)
        )
        player = RecordingPlayer()
        robot = Robot(hub, CountingMic([utterance_fixture()]), player, capabilities=CONTINUATION)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: len(player.played) == 1)
        turns = (await owner(hub, "GET", "/robot-voice")).json()["session"]["turns"]
        assert [(t["transcript"], t["segments"], t["outcome"]) for t in turns] == [("So I went to the", 1, "spoken")]
        await robot.voice.aclose()

    asyncio.run(scenario())


def test_stop_while_a_turn_is_held_answers_nothing() -> None:
    async def scenario():
        tts = FixedTTS()
        hub = make_hub(
            ScriptedSTT("I was wondering"), tts, limits=VoiceLimits(playback_tail_guard_ms=0, continuation_window_ms=5000)
        )
        player = RecordingPlayer()
        mic = CountingMic([utterance_fixture()])
        robot = Robot(hub, mic, player, capabilities=CONTINUATION)
        await robot.connect()
        start = (await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})).json()
        manager = hub.state.robot_voice_manager
        await wait_until(lambda: manager.get(start["voice_session_id"]).held is not None)

        await owner(hub, "POST", "/robot-voice/stop", json={"voice_session_id": start["voice_session_id"]})
        await wait_until(lambda: robot.state.embodiment_state == EmbodimentState.IDLE)
        await asyncio.sleep(0.3)
        assert player.played == [] and tts.spoken == []
        session = (await owner(hub, "GET", "/robot-voice")).json()["session"]
        assert (session["state"], session["turns"]) == ("stopped", [])
        assert mic._started_at is None  # microphone closed, and not reopened
        await robot.voice.aclose()

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



@pytest.mark.slow
@pytest.mark.skipif(espeak_binary is None, reason="espeak-ng not installed on PATH")
def test_real_speech_with_a_mid_sentence_pause_is_one_turn() -> None:
    """Phase 24e: real Silero cuts at the pause, real Whisper transcribes
    the first half (with whatever punctuation it adds), and the hub holds it
    until the rest arrives."""
    from reachy_embodiment.audio.vad import VoiceActivityDetector
    from reachy_hub.stt import FasterWhisperSTT

    async def scenario():
        tts = FixedTTS()
        hub = make_hub(FasterWhisperSTT(model_size="tiny.en"), tts)
        player = RecordingPlayer()
        speech = np.concatenate([
            _espeak_16k("I was wondering if you could tell me"), silence(1.0), _espeak_16k("what time it is in London"),
        ])
        robot = Robot(hub, SimulatedMicSource([speech]), player, capabilities=CONTINUATION)
        robot.voice._vad_factory = lambda limits: VoiceActivityDetector(
            min_silence_duration_ms=limits.end_of_speech_silence_ms
        )
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: len(player.played) == 1, timeout=120)
        turns = (await owner(hub, "GET", "/robot-voice")).json()["session"]["turns"]
        assert len(turns) == 1 and turns[0]["segments"] == 2, turns
        assert "wondering" in turns[0]["transcript"].lower() and "london" in turns[0]["transcript"].lower()
        assert len(tts.spoken) == 1
        await robot.voice.aclose()

    asyncio.run(scenario())

def test_simulated_backend_exposes_a_microphone_and_stop() -> None:
    backend = SimulatedRobotBackend()
    assert isinstance(backend.open_microphone(), SimulatedMicSource)
    backend.stop_audio()


# --- conversational motion (Phase 24f) --------------------------------------


class MotionRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def play_behaviour(self, name, parameters) -> None:
        self.calls.append(("play", name))

    def stop_motion(self) -> None:
        self.calls.append(("stop",))

    def goto_home(self) -> None:
        self.calls.append(("home",))

    def set_speech_wobble(self, enabled: bool) -> None:
        self.calls.append(("wobble", enabled))


def test_conversation_drives_motion_and_a_stop_holds_without_going_home() -> None:
    async def scenario():
        hub = make_hub(ScriptedSTT("hello reachy"), FixedTTS(seconds=30))
        player = RecordingPlayer()
        motion = MotionRecorder()
        robot = Robot(hub, CountingMic([utterance_fixture()]), player, motion_backend=motion)
        await robot.connect()
        start = (await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})).json()
        await wait_until(lambda: ("wobble", True) in motion.calls)
        assert ("play", Behaviour.LISTENING) in motion.calls
        assert ("play", Behaviour.THINKING) in motion.calls
        assert motion.calls.index(("play", Behaviour.LISTENING)) < motion.calls.index(("play", Behaviour.THINKING))
        # The conversation owns motion: an explicit behaviour is refused.
        assert robot.motion.request_behaviour(Behaviour.GREETING, {}) is False

        # Thinking started from home, since listening left the head away.
        assert motion.calls.index(("home",)) < motion.calls.index(("play", Behaviour.THINKING))
        homes = motion.calls.count(("home",))
        await owner(hub, "POST", "/robot-voice/stop", json={"voice_session_id": start["voice_session_id"]})
        assert player.stopped == 1
        await wait_until(lambda: motion.calls[-2:] == [("wobble", False), ("stop",)])
        await asyncio.sleep(0.2)
        assert motion.calls.count(("home",)) == homes  # a stop holds; no return home
        assert not robot.motion.conversation_owns_motion
        await robot.voice.aclose()
        robot.motion.close()

    asyncio.run(scenario())


def test_session_limit_is_a_normal_end_and_returns_home_once() -> None:
    async def scenario():
        hub = make_hub(ScriptedSTT(), FixedTTS(), limits=VoiceLimits(max_session_seconds=0.3))
        motion = MotionRecorder()
        robot = Robot(hub, CountingMic([]), RecordingPlayer(), motion_backend=motion)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: ("home",) in motion.calls)
        await asyncio.sleep(0.2)
        assert motion.calls.count(("home",)) == 1
        robot.motion.close()

    asyncio.run(scenario())


def test_withheld_reply_gets_no_speaking_motion() -> None:
    async def scenario():
        hub = make_hub(ScriptedSTT("what is on my calendar", "hello"), FixedTTS())
        player = RecordingPlayer()
        motion = MotionRecorder()
        robot = Robot(hub, CountingMic([utterance_fixture(), utterance_fixture()]), player, motion_backend=motion)
        await robot.connect()
        await owner(hub, "POST", "/robot-voice/start", json={"robot_id": ROBOT_ID})
        await wait_until(lambda: len(player.played) == 1 and ("wobble", True) in motion.calls)
        turns = (await owner(hub, "GET", "/robot-voice")).json()["session"]["turns"]
        assert [t["outcome"] for t in turns] == ["withheld", "spoken"]
        # Only the spoken second turn wobbled.
        assert motion.calls.count(("wobble", True)) == 1
        await robot.voice.aclose()
        robot.motion.close()

    asyncio.run(scenario())
