"""Phase 24g wake monitoring, robot side (ADR 0023 wake-started sessions).

The monitor runs against a microphone the test feeds chunk by chunk, a
deterministic detector and VAD, and a controlled clock; no model, daemon
or hub. The conversation half (primed turn 1, follow-up timeout) drives
the real VoiceConversation with a scripted uploader. The control-socket
test uses a real local websockets server, like test_robot_ws_client.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time

import numpy as np
import websockets
from reachy_embodiment.motion import ALERT_POSE, SLEEP_POSE, MotionController
from reachy_embodiment.robot_ws_client import RobotWSClient
from reachy_embodiment.state import ServiceState
from reachy_embodiment.voice import VoiceConversation, VoiceSessionGone
from reachy_embodiment.wake import WakeMonitor

from shared.models.embodiment import Behaviour
from shared.models.robot_voice import (
    WAKE_CAPABILITY,
    VoiceLimits,
    VoiceTurnOutcome,
    WakeLimits,
)
from shared.models.robot_ws import VoiceStartMessage, WakeArmMessage, WSMessageType

SR = 16000
CHUNK = 0.1  # seconds per microphone read
WAKE_AMPLITUDE = 0.9


def tone(seconds: float, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype=np.float32)


def wake_phrase(seconds: float = 0.5) -> np.ndarray:
    return tone(seconds, WAKE_AMPLITUDE)


class EnergyVAD:
    """Loud chunk starts speech; five quiet chunks (160 ms) end it."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.speaking, self.quiet = False, 0

    def process_chunk(self, chunk: np.ndarray) -> dict | None:
        loud = float(np.sqrt(np.mean(chunk**2))) > 0.05
        if not self.speaking:
            if loud:
                self.speaking, self.quiet = True, 0
                return {"start": 0}
            return None
        self.quiet = 0 if loud else self.quiet + 1
        if self.quiet >= 5:
            self.reset()
            return {"end": 0}
        return None


class ChunkMic:
    """Serves what the test pushed one CHUNK at a time, like a live stream."""

    def __init__(self) -> None:
        self.queue: list[np.ndarray] = []
        self.open = False
        self.starts = 0
        self.lock = threading.Lock()

    def push(self, samples: np.ndarray) -> None:
        step = int(CHUNK * SR)
        with self.lock:
            self.queue.extend(samples[i : i + step] for i in range(0, len(samples), step))

    def start(self) -> None:
        self.open, self.starts = True, self.starts + 1

    def read(self) -> np.ndarray | None:
        with self.lock:
            if not self.open or not self.queue:
                return None
            return self.queue.pop(0)

    def stop(self) -> None:
        self.open = False
        with self.lock:
            self.queue = []


class LoudDetector:
    """Scores 1.0 when the window holds the loud wake marker."""

    window_seconds = 1.0

    def __init__(self) -> None:
        self.closed = False

    def score(self, samples: np.ndarray) -> float:
        assert len(samples) == SR
        return 1.0 if float(np.max(np.abs(samples))) > WAKE_AMPLITUDE * 0.9 else 0.0

    def close(self) -> None:
        self.closed = True


class FakeConversation:
    def __init__(self) -> None:
        self.voice_session_id: str | None = None
        self.primed: np.ndarray | None = None

    def prime(self, utterance):
        self.primed = utterance


HOLD = object()  # an upload the hub answers only after voice_start


class ScriptedCandidates:
    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.uploads: list[tuple[int, str, int]] = []

    async def wake_candidate(self, wav_bytes, *, arm_id, generation):
        # 44-byte WAV header, 16-bit samples.
        self.uploads.append(((len(wav_bytes) - 44) // 2, arm_id, generation))
        answer = self.answers.pop(0)
        if answer is HOLD:
            await asyncio.Event().wait()  # as the hub: voice_start comes first
        if isinstance(answer, Exception):
            raise answer
        return answer


class RecordingMotion:
    def __init__(self) -> None:
        self.moves: list[str] = []

    def rest_move(self, pose: str) -> bool:
        self.moves.append(pose)
        return True


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def wait_until(predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.005)


def make_monitor(uploader, *, conversation=None, limits: WakeLimits | None = None, detector=None, alert_threshold=None):
    mic, motion, clock = ChunkMic(), RecordingMotion(), Clock()
    conversation = conversation or FakeConversation()
    monitor = WakeMonitor(
        lambda: mic,
        detector or LoudDetector,
        lambda limits: EnergyVAD(),
        uploader,
        conversation,
        motion=motion,
        poll_interval=0.001,
        idle_interval=0.005,
        admission_wait=5.0,
        alert_threshold=alert_threshold,
        clock=clock,
    )
    arm = WakeArmMessage(arm_id="arm-1", limits=limits or WakeLimits())
    return monitor, mic, motion, clock, conversation, arm


def test_rejected_candidate_uploads_phrase_and_request_then_rests_and_listens_again() -> None:
    async def scenario():
        uploader = ScriptedCandidates(None)
        monitor, mic, motion, _, conversation, arm = make_monitor(uploader)
        await monitor.arm(arm, generation=3)
        await wait_until(lambda: mic.open)
        assert motion.moves == ["sleep"]  # rests before listening

        mic.push(np.concatenate([silence(1.0), wake_phrase(), tone(1.5), silence(0.4)]))
        await wait_until(lambda: len(uploader.uploads) == 1)
        samples, arm_id, generation = uploader.uploads[0]
        assert (arm_id, generation) == ("arm-1", 3)
        assert samples >= int(2.0 * SR)  # the phrase and the request together
        assert motion.moves[:2] == ["sleep", "alert"]

        await wait_until(lambda: mic.starts == 2 and mic.open)
        assert motion.moves == ["sleep", "alert", "sleep"]
        assert conversation.primed is None
        await monitor.aclose()
        assert not mic.open

    asyncio.run(scenario())


class MediumDetector(LoudDetector):
    def score(self, samples: np.ndarray) -> float:
        return 0.8 if super().score(samples) else 0.0


def test_a_detection_below_the_alert_threshold_is_captured_without_raising_the_head() -> None:
    async def scenario():
        uploader = ScriptedCandidates(None)
        monitor, mic, motion, _, _, arm = make_monitor(uploader, detector=MediumDetector, alert_threshold=0.9)
        await monitor.arm(arm, generation=3)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([silence(1.0), wake_phrase(), tone(1.5), silence(0.4)]))
        await wait_until(lambda: len(uploader.uploads) == 1)
        await wait_until(lambda: mic.starts == 2 and mic.open)
        assert motion.moves == ["sleep"]
        await monitor.aclose()

    asyncio.run(scenario())


def test_a_detection_at_or_above_the_alert_threshold_raises_the_head() -> None:
    async def scenario():
        uploader = ScriptedCandidates(None)
        monitor, mic, motion, _, _, arm = make_monitor(uploader, detector=MediumDetector, alert_threshold=0.8)
        await monitor.arm(arm, generation=3)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([silence(1.0), wake_phrase(), tone(1.5), silence(0.4)]))
        await wait_until(lambda: motion.moves[:2] == ["sleep", "alert"])
        await monitor.aclose()

    asyncio.run(scenario())


def test_wake_then_silence_is_discarded_on_the_robot() -> None:
    async def scenario():
        uploader = ScriptedCandidates()
        monitor, mic, motion, clock, _, arm = make_monitor(uploader)
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([silence(1.0), wake_phrase(), silence(0.6)]))
        await wait_until(lambda: motion.moves == ["sleep", "alert"])
        await asyncio.sleep(0.05)
        clock.now += 5.9  # still inside the speech-start allowance
        await asyncio.sleep(0.05)
        assert mic.starts == 1
        clock.now += 0.2
        await wait_until(lambda: mic.starts == 2)
        assert uploader.uploads == []
        assert motion.moves == ["sleep", "alert", "sleep"]
        await monitor.aclose()

    asyncio.run(scenario())


def test_natural_pause_joins_the_phrase_and_the_request_into_one_candidate() -> None:
    async def scenario():
        uploader = ScriptedCandidates(None)
        monitor, mic, _, clock, _, arm = make_monitor(uploader)
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([silence(1.0), wake_phrase(), silence(0.6)]))
        await asyncio.sleep(0.1)
        clock.now += 1.5  # a natural pause, under the 6 s allowance
        mic.push(np.concatenate([tone(1.2), silence(0.4)]))
        await wait_until(lambda: len(uploader.uploads) == 1)
        assert uploader.uploads[0][0] >= int(1.6 * SR)
        await monitor.aclose()

    asyncio.run(scenario())


def test_admitted_candidate_is_primed_and_the_head_comes_home_for_the_session() -> None:
    async def scenario():
        # The hub opens the session, sending voice_start, before it answers
        # the upload; the control client then suspends monitoring.
        uploader = ScriptedCandidates(HOLD)
        monitor, mic, motion, _, conversation, arm = make_monitor(uploader)
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([silence(1.0), wake_phrase(), tone(1.5), silence(0.4)]))
        await wait_until(lambda: len(uploader.uploads) == 1)
        assert conversation.primed is not None and len(conversation.primed) >= int(2.0 * SR)

        conversation.voice_session_id = "sid-1"
        await monitor.suspend()
        assert mic.starts == 1 and not mic.open  # the microphone is the session's now
        await wait_until(lambda: motion.moves == ["sleep", "alert", "home"])

        conversation.voice_session_id = None  # the session ended
        monitor.resume()
        await wait_until(lambda: mic.starts == 2 and mic.open)
        assert motion.moves == ["sleep", "alert", "home", "sleep"]
        await monitor.aclose()

    asyncio.run(scenario())


def test_an_admission_answered_before_voice_start_still_brings_the_head_home() -> None:
    async def scenario():
        uploader = ScriptedCandidates("sid-1")
        monitor, mic, motion, _, conversation, arm = make_monitor(uploader)
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([silence(1.0), wake_phrase(), tone(1.5), silence(0.4)]))
        await wait_until(lambda: len(uploader.uploads) == 1)
        await asyncio.sleep(0.05)  # the answer is in; monitoring waits for the session
        conversation.voice_session_id = "sid-1"
        await monitor.suspend()
        await wait_until(lambda: motion.moves == ["sleep", "alert", "home"])
        await monitor.aclose()

    asyncio.run(scenario())


def test_a_session_started_without_a_candidate_does_not_move_the_head() -> None:
    async def scenario():
        monitor, mic, motion, _, _, arm = make_monitor(ScriptedCandidates())
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        await monitor.suspend()  # e.g. the owner started a session from the panel
        await asyncio.sleep(0.05)
        assert motion.moves == ["sleep"]
        await monitor.aclose()

    asyncio.run(scenario())


def test_stale_arm_stops_monitoring_until_armed_again() -> None:
    async def scenario():
        uploader = ScriptedCandidates(VoiceSessionGone("409"))
        monitor, mic, _, _, conversation, arm = make_monitor(uploader)
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        mic.push(np.concatenate([silence(1.0), wake_phrase(), tone(1.5), silence(0.4)]))
        await wait_until(lambda: len(uploader.uploads) == 1)
        await wait_until(lambda: not monitor.listening)
        assert mic.starts == 1 and not mic.open and conversation.primed is None

        await monitor.arm(WakeArmMessage(arm_id="arm-2"), generation=1)
        await wait_until(lambda: mic.starts == 2)
        await monitor.aclose()

    asyncio.run(scenario())


def test_suspend_releases_the_microphone_and_disarm_moves_nothing() -> None:
    async def scenario():
        monitor, mic, motion, _, _, arm = make_monitor(ScriptedCandidates())
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        await monitor.suspend()
        assert not mic.open and not monitor.listening
        monitor.resume()
        await wait_until(lambda: mic.starts == 2 and mic.open)
        assert motion.moves == ["sleep", "sleep"]  # a session may have moved it

        await monitor.disarm()
        assert not mic.open and not monitor.armed
        monitor.resume()  # not armed: nothing restarts
        await asyncio.sleep(0.05)
        assert mic.starts == 2 and motion.moves == ["sleep", "sleep"]
        await monitor.aclose()

    asyncio.run(scenario())


def test_hub_disarm_during_a_conversation_rests_once_when_it_ends() -> None:
    async def scenario():
        monitor, mic, motion, _, conversation, arm = make_monitor(ScriptedCandidates())
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        await monitor.suspend()
        conversation.voice_session_id = "session"
        await monitor.arm(WakeArmMessage(arm_id=None, limits=WakeLimits()), generation=1)
        assert motion.moves == ["sleep"]  # disarming moves nothing by itself

        conversation.voice_session_id = None
        monitor.resume()
        await wait_until(lambda: motion.moves == ["sleep", "sleep"])
        monitor.resume()  # once only; not armed, so nothing else restarts
        await asyncio.sleep(0.05)
        assert motion.moves == ["sleep", "sleep"] and not monitor.listening
        await monitor.aclose()

    asyncio.run(scenario())


def test_hub_disarm_of_an_armed_monitor_with_no_conversation_rests_once() -> None:
    async def scenario():
        monitor, mic, motion, _, _, arm = make_monitor(ScriptedCandidates())
        await monitor.arm(arm, generation=1)
        await wait_until(lambda: mic.open)
        disarm = WakeArmMessage(arm_id=None, limits=WakeLimits())
        await monitor.arm(disarm, generation=1)
        await wait_until(lambda: motion.moves == ["sleep", "sleep"])
        await monitor.arm(disarm, generation=1)  # a repeat or reconnect disarm
        monitor.resume()
        await asyncio.sleep(0.05)
        assert motion.moves == ["sleep", "sleep"]
        await monitor.aclose()

    asyncio.run(scenario())


# --- the conversation side --------------------------------------------------


class ScriptedUploader:
    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple] = []

    async def post(self, wav, *, voice_session_id, turn, generation, segment=1):
        self.calls.append(("post", turn, segment, (len(wav) - 44) // 2))
        return self.outcomes.pop(0), None

    async def finalize(self, *, voice_session_id, turn, generation):
        self.calls.append(("finalize", turn))
        return self.outcomes.pop(0), None

    async def aclose(self) -> None:
        pass


class RecordingPlayer:
    def play_audio(self, wav_bytes: bytes) -> float:
        return 0.0

    def stop_audio(self) -> None:
        pass


def test_wake_session_answers_the_primed_candidate_then_ends_without_follow_up() -> None:
    async def scenario():
        mic, clock, idle = ChunkMic(), Clock(), []
        uploader = ScriptedUploader(VoiceTurnOutcome.WITHHELD)
        voice = VoiceConversation(
            lambda: mic, lambda limits: EnergyVAD(), uploader, RecordingPlayer(),
            ServiceState(connected=True, sim=True), poll_interval=0.001, clock=clock,
            on_idle=lambda: idle.append(True),
        )
        reports: list[tuple[str, str | None]] = []

        async def report(message):
            reports.append((message.state.value, message.detail))

        limits = VoiceLimits(pre_roll_ms=0, playback_tail_guard_ms=0, continuation_window_ms=0)
        voice.prime(tone(2.0))
        start = VoiceStartMessage(voice_session_id="s", limits=limits, wake_started=True, follow_up_seconds=10.0)
        await voice.start(start, 1, report)
        # Turn 1 is the candidate itself: uploaded without capturing again.
        await wait_until(lambda: len(uploader.calls) == 1)
        assert uploader.calls[0] == ("post", 1, 1, 2 * SR)

        await wait_until(lambda: [state for state, _ in reports].count("listening") == 2)
        clock.now += 9.9  # nobody speaks
        await asyncio.sleep(0.05)
        assert voice.voice_session_id == "s"
        clock.now += 0.2
        await wait_until(lambda: voice.voice_session_id is None)
        assert reports[-1] == ("stopped", "No follow-up heard")
        assert idle == [True] and not mic.open and len(uploader.calls) == 1
        await voice.aclose()

    asyncio.run(scenario())


def test_owner_started_session_ignores_a_primed_candidate() -> None:
    async def scenario():
        mic = ChunkMic()
        uploader = ScriptedUploader(VoiceTurnOutcome.WITHHELD)
        voice = VoiceConversation(
            lambda: mic, lambda limits: EnergyVAD(), uploader, RecordingPlayer(),
            ServiceState(connected=True, sim=True), poll_interval=0.001,
        )

        async def report(message):
            pass

        voice.prime(tone(2.0))
        limits = VoiceLimits(pre_roll_ms=0, playback_tail_guard_ms=0, continuation_window_ms=0)
        await voice.start(VoiceStartMessage(voice_session_id="s", limits=limits), 1, report)
        await wait_until(lambda: mic.open)
        await asyncio.sleep(0.05)
        assert uploader.calls == []  # it waits for speech, as before 24g
        await voice.aclose()

    asyncio.run(scenario())


# --- control socket ------------------------------------------------------------


class RecordingWake:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def arm(self, message, generation):
        self.events.append(f"arm {message.arm_id} {generation}")

    async def disarm(self):
        self.events.append("disarm")

    async def suspend(self):
        self.events.append("suspend")


class RecordingVoice:
    def __init__(self, events) -> None:
        self.events = events

    async def start(self, message, generation, send_state):
        self.events.append(f"start {message.voice_session_id}")

    async def stop(self, voice_session_id=None):
        pass


def test_control_socket_arms_suspends_before_a_session_and_disarms_on_disconnect() -> None:
    received: dict = {}
    done = asyncio.Event()

    async def handler(ws):
        register = json.loads(await ws.recv())
        received["capabilities"] = register["capabilities"]
        await ws.send(json.dumps({"type": WSMessageType.REGISTERED, "robot_id": "nano-1", "generation": 4}))
        await ws.send(WakeArmMessage(arm_id="arm-1").model_dump_json())
        await ws.send(VoiceStartMessage(voice_session_id="sid").model_dump_json())
        await asyncio.sleep(0.1)
        done.set()

    async def scenario():
        wake = RecordingWake()
        voice = RecordingVoice(wake.events)
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            client = RobotWSClient(url, "nano-1", "tok", voice=voice, wake=wake)  # type: ignore[arg-type]
            task = asyncio.create_task(client.run())
            try:
                await asyncio.wait_for(done.wait(), timeout=2.0)
                await wait_until(lambda: "disarm" in wake.events)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        assert WAKE_CAPABILITY in received["capabilities"]
        assert wake.events[:4] == ["arm arm-1 4", "suspend", "start sid", "disarm"]

    asyncio.run(scenario())


# --- motion -------------------------------------------------------------------


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.started = True

    def play_behaviour(self, name, parameters) -> bool:
        self.calls.append(f"behaviour {name.value}")
        return self.started

    def stop_motion(self) -> None:
        self.calls.append("stop")

    def goto_home(self) -> None:
        self.calls.append("home")

    def goto_pose(self, pose) -> None:
        self.calls.append("alert" if pose == ALERT_POSE else "sleep" if pose == SLEEP_POSE else "pose")

    def set_speech_wobble(self, enabled: bool) -> None:
        self.calls.append(f"wobble {enabled}")


def test_rest_moves_need_the_switch_and_yield_to_a_conversation_or_remote_control() -> None:
    backend = RecordingBackend()
    off = MotionController(backend, ServiceState(connected=True, sim=True), threaded=False)
    assert off.rest_move("sleep") is False and backend.calls == []

    state = ServiceState(connected=True, sim=True)
    waits: list[float] = []
    motion = MotionController(
        backend, state, wake_animation=True, conversation_motion=True, threaded=False, sleep=waits.append
    )
    # From an unknown pose the head goes home and, once there, down; after
    # that every rest move is one silent goto. No daemon routine is used.
    assert motion.rest_move("sleep") and waits == [1.2]
    assert motion.rest_move("alert") and motion.rest_move("home") and motion.rest_move("sleep")
    assert backend.calls == ["home", "sleep", "alert", "home", "sleep"]
    assert motion.rest_move("alert") and motion.rest_move("sleep")  # a false wake
    assert backend.calls[-2:] == ["alert", "sleep"] and waits == [1.2]
    motion.stop()  # any other motion forgets the rest pose
    backend.calls.clear()
    assert motion.rest_move("sleep") and backend.calls == ["home", "sleep"] and waits == [1.2, 1.2]

    token = motion.begin_conversation()
    assert motion.rest_move("sleep") is False
    motion.end_conversation(token, completed=False)
    state.remote_active = True
    assert motion.rest_move("sleep") is False
    motion.close()


def test_idle_behaviours_without_a_move_keep_the_rest_pose() -> None:
    # Presence asks for idle behaviours every few seconds; they map to no
    # move. Forgetting the pose made every false wake fall back to a noisy
    # path (24g first physical run).
    backend = RecordingBackend()
    waits: list[float] = []
    motion = MotionController(
        backend, ServiceState(connected=True, sim=True), wake_animation=True, threaded=False, sleep=waits.append
    )
    motion.rest_move("sleep")
    backend.started = False
    motion.request_behaviour(Behaviour.IDLE_BREATHING, {}, idle=True)
    backend.calls.clear()
    assert motion.rest_move("alert") and motion.rest_move("sleep")
    assert backend.calls == ["alert", "sleep"] and waits == [1.2]

    backend.started = True  # a move that did start leaves the pose unknown
    motion.request_behaviour(Behaviour.GREETING, {})
    backend.calls.clear()
    assert motion.rest_move("sleep") and backend.calls == ["home", "sleep"]
    motion.close()


def test_wake_animation_is_on_by_default_and_the_env_file_can_turn_it_off(monkeypatch) -> None:
    from reachy_embodiment.app import _default_motion_controller

    backend = RecordingBackend()
    state = ServiceState(connected=True, sim=True)
    monkeypatch.delenv("WAKE_ANIMATION_ENABLED", raising=False)
    motion = _default_motion_controller(backend, state)
    assert motion.rest_move("alert") and backend.calls == ["alert"]
    motion.close()

    monkeypatch.setenv("WAKE_ANIMATION_ENABLED", "false")
    motion = _default_motion_controller(backend, state)
    assert motion.rest_move("alert") is False
    motion.close()
