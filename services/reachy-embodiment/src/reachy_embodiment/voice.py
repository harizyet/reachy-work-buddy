"""Robot-side conversation loop (Phase 24c, ADR 0023).

Runs only inside a session the hub started over the ADR 0019 control
socket. Each turn: open the microphone, let Silero VAD find one bounded
utterance, close the microphone, upload it to the hub with this robot's
credential, then play the reply (if the hub permitted speech) through the
daemon. Half-duplex: the microphone is closed while uploading, waiting and
speaking, plus a tail guard, so the robot cannot transcribe itself.

Adaptive end of turn (Phase 24e, ADR 0023 addendum): within one turn the
microphone stays open while a segment uploads. If the hub answers
`continue` (the segment sounded unfinished), the next segment of the same
turn is captured from that audio; if no speech starts within the
continuation window, the robot asks the hub to finalize the held turn. Any
other outcome discards the audio and closes the microphone before playback.

Open-palm stop (Phase 24e item 5): when the hub turns it on for the
session and a `StopGesture` is supplied, camera frames go to the hub during
playback. When the hub sees a held open palm, the daemon's audio stops and
the loop moves straight on to the next listening turn in the same session;
it does not end the conversation.

Stopping cancels the loop wherever it is: capture closes the microphone,
an in-flight upload is abandoned, and playback is stopped on the daemon
(`stop_audio`), not merely left to finish. Nothing here restarts capture on
its own; after a stop or disconnect only a new `voice_start` does.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import math
import wave
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
import numpy as np

from reachy_embodiment.audio.vad import CHUNK_SAMPLES
from reachy_embodiment.gesture import PalmStopGone
from reachy_embodiment.motion import MotionController
from reachy_embodiment.state import ServiceState
from shared.models.embodiment import EmbodimentState
from shared.models.robot_voice import (
    MIN_CONTINUATION_SECONDS,
    ROBOT_GENERATION_HEADER,
    SAMPLE_RATE,
    VOICE_OUTCOME_HEADER,
    VOICE_SEGMENT_HEADER,
    VOICE_SESSION_HEADER,
    VOICE_TURN_HEADER,
    PalmFrameResult,
    RobotVoiceState,
    VoiceLimits,
    VoiceTurnOutcome,
)
from shared.models.robot_ws import VoiceStartMessage, VoiceStateMessage
from shared.protocols.robot_ws import (
    ROBOT_PALM_FRAME,
    ROBOT_VOICE_TURN,
    ROBOT_VOICE_TURN_FINALIZE,
)

log = logging.getLogger(__name__)

# Daemon play_sound starts asynchronously; wait this long past the WAV's
# own duration before treating playback as finished.
PLAYBACK_MARGIN_SECONDS = 0.3


class ChunkVAD(Protocol):
    def reset(self) -> None: ...

    def process_chunk(self, chunk: np.ndarray) -> dict[str, int] | None: ...


class MicSource(Protocol):
    """Mono float32 samples at 16 kHz. `read` returns whatever arrived
    since the last call (any length), or None if nothing did."""

    def start(self) -> None: ...

    def read(self) -> np.ndarray | None: ...

    def stop(self) -> None: ...


class SpeakerPlayer(Protocol):
    def play_audio(self, wav_bytes: bytes) -> float: ...

    def stop_audio(self) -> None: ...


class StopGesture(Protocol):
    async def prepare(self) -> bool: ...

    async def wait(self, voice_session_id: str, turn: int, generation: int) -> None: ...

    def close(self) -> None: ...


class UtteranceSegmenter:
    """Turns a microphone stream into at most one utterance per listening
    phase. VAD decides where speech starts and ends; the maximum length is
    enforced here regardless of what VAD reports."""

    def __init__(self, vad: ChunkVAD, limits: VoiceLimits) -> None:
        self._vad = vad
        self._max_seconds = limits.max_utterance_seconds
        self._max_chunks = self._chunks(self._max_seconds)
        self._min_samples = int(limits.min_utterance_ms * SAMPLE_RATE / 1000)
        self._preroll: deque[np.ndarray] = deque(
            maxlen=max(1, math.ceil(limits.pre_roll_ms * SAMPLE_RATE / 1000 / CHUNK_SAMPLES))
        )
        self._pending = np.empty(0, dtype=np.float32)
        self._speech: list[np.ndarray] | None = None

    @staticmethod
    def _chunks(seconds: float) -> int:
        return max(1, math.ceil(seconds * SAMPLE_RATE / CHUNK_SAMPLES))

    @property
    def in_speech(self) -> bool:
        """VAD has found speech that has not ended yet."""
        return self._speech is not None

    def limit(self, seconds: float) -> None:
        """Cap the next utterance at what remains of a held turn's budget."""
        self._max_chunks = self._chunks(seconds)

    def reset(self) -> None:
        self._vad.reset()
        self._preroll.clear()
        self._pending = np.empty(0, dtype=np.float32)
        self._speech = None
        self._max_chunks = self._chunks(self._max_seconds)

    def feed(self, samples: np.ndarray) -> np.ndarray | None:
        self._pending = np.concatenate([self._pending, samples.astype(np.float32, copy=False)])
        while len(self._pending) >= CHUNK_SAMPLES:
            chunk = self._pending[:CHUNK_SAMPLES]
            self._pending = self._pending[CHUNK_SAMPLES:]
            event = self._vad.process_chunk(chunk)
            if self._speech is None:
                if event is not None and "start" in event:
                    self._speech = [*self._preroll, chunk]
                    self._preroll.clear()
                else:
                    self._preroll.append(chunk)
                continue

            self._speech.append(chunk)
            ended = event is not None and "end" in event
            if not ended and len(self._speech) < self._max_chunks:
                continue
            utterance = np.concatenate(self._speech)
            self._speech = None
            self._vad.reset()
            if ended and len(utterance) < self._min_samples:
                continue  # a click or cough, not a turn; keep listening
            return utterance
        return None


def encode_wav(samples: np.ndarray) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


def _as_http_url(url: str) -> str:
    if url.startswith("wss://"):
        return "https://" + url[len("wss://") :]
    if url.startswith("ws://"):
        return "http://" + url[len("ws://") :]
    return url


class MicrophoneFailed(Exception):
    """Capture could not start or read; the session ends."""


class VoiceSessionGone(Exception):
    """The hub refused the turn (session gone, stale connection or bad
    credential); this session's loop ends rather than retrying."""


class VoiceTurnClient:
    """Uploads one utterance to the hub (ADR 0019's robot-initiated media
    path) and returns the hub's decision plus reply audio, if any."""

    def __init__(
        self,
        hub_url: str,
        robot_id: str,
        token: str,
        *,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._robot_id = robot_id
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=_as_http_url(hub_url.rstrip("/")), timeout=timeout, transport=transport
        )

    def _headers(self, voice_session_id: str, turn: int, generation: int) -> dict[str, str]:
        return {
            "X-Robot-Id": self._robot_id,
            "Authorization": f"Bearer {self._token}",
            ROBOT_GENERATION_HEADER: str(generation),
            VOICE_SESSION_HEADER: voice_session_id,
            VOICE_TURN_HEADER: str(turn),
        }

    async def post(
        self, wav_bytes: bytes, *, voice_session_id: str, turn: int, generation: int, segment: int = 1
    ) -> tuple[VoiceTurnOutcome, bytes | None]:
        headers = self._headers(voice_session_id, turn, generation)
        headers["Content-Type"] = "audio/wav"
        headers[VOICE_SEGMENT_HEADER] = str(segment)
        return self._outcome(await self._client.post(ROBOT_VOICE_TURN, content=wav_bytes, headers=headers))

    async def palm_frame(self, jpeg: bytes, voice_session_id: str, turn: int, generation: int) -> bool:
        """Send one playback frame; True when the hub says stop the reply.
        Raises PalmStopGone once the hub stops accepting frames for it."""
        headers = self._headers(voice_session_id, turn, generation)
        headers["Content-Type"] = "image/jpeg"
        response = await self._client.post(ROBOT_PALM_FRAME, content=jpeg, headers=headers, timeout=5.0)
        if response.status_code in (401, 404, 409):
            raise PalmStopGone(f"hub refused palm frame: {response.status_code}")
        response.raise_for_status()
        return PalmFrameResult.model_validate(response.json()).stop

    async def finalize(
        self, *, voice_session_id: str, turn: int, generation: int
    ) -> tuple[VoiceTurnOutcome, bytes | None]:
        """Ask the hub to answer the turn it is holding."""
        headers = self._headers(voice_session_id, turn, generation)
        return self._outcome(await self._client.post(ROBOT_VOICE_TURN_FINALIZE, headers=headers))

    @staticmethod
    def _outcome(response: httpx.Response) -> tuple[VoiceTurnOutcome, bytes | None]:
        if response.status_code in (401, 404, 409):
            raise VoiceSessionGone(f"hub rejected turn: {response.status_code}")
        try:
            outcome = VoiceTurnOutcome(response.headers.get(VOICE_OUTCOME_HEADER, ""))
        except ValueError:
            response.raise_for_status()
            raise httpx.HTTPError(f"hub reply had no turn outcome ({response.status_code})") from None
        if outcome == VoiceTurnOutcome.SPOKEN and response.status_code == 200:
            return outcome, response.content
        return outcome, None

    async def aclose(self) -> None:
        await self._client.aclose()


SendState = Callable[[VoiceStateMessage], Awaitable[None]]


class VoiceConversation:
    def __init__(
        self,
        microphone_factory: Callable[[], MicSource],
        vad_factory: Callable[[VoiceLimits], ChunkVAD],
        uploader: VoiceTurnClient,
        player: SpeakerPlayer,
        service_state: ServiceState,
        *,
        poll_interval: float = 0.01,
        clock: Callable[[], float] | None = None,
        stop_gesture: StopGesture | None = None,
        motion: MotionController | None = None,
    ) -> None:
        self._microphone_factory = microphone_factory
        self._vad_factory = vad_factory
        self._uploader = uploader
        self._player = player
        self._state = service_state
        self._poll_interval = poll_interval
        # Session deadline and continuation window; injectable for
        # controlled-time tests.
        self._clock = clock or (lambda: asyncio.get_running_loop().time())
        self._task: asyncio.Task[None] | None = None
        self._session_id: str | None = None
        self._stop_gesture = stop_gesture
        # Set per session once the watcher's detector and camera are ready.
        self._palm_stop_ready = False
        # Phase 24f: conversation states drive local motion through this,
        # fenced by the token from begin_conversation.
        self._motion = motion
        self._motion_token: int | None = None

    @property
    def voice_session_id(self) -> str | None:
        return self._session_id

    async def start(self, message: VoiceStartMessage, generation: int, send_state: SendState) -> None:
        await self.stop()
        log.info("voice start received (session %s…)", message.voice_session_id[:4])
        self._session_id = message.voice_session_id
        self._task = asyncio.create_task(self._run(message, generation, send_state))

    async def stop(self, voice_session_id: str | None = None) -> None:
        if voice_session_id is not None and voice_session_id != self._session_id:
            return
        task, self._task, self._session_id = self._task, None, None
        if task is not None and not task.done():
            # Stop-tail anchors: the matrix times the audible tail from the
            # stop reaching the robot.
            log.info("voice stop received")
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            log.info("voice stop complete")

    async def aclose(self) -> None:
        await self.stop()
        await self._uploader.aclose()
        if self._stop_gesture is not None:
            await asyncio.to_thread(self._stop_gesture.close)

    def _set_state(self, state: EmbodimentState | None, turn: int = 0) -> None:
        if state is None:
            # The session is ending; end_conversation decides the motion.
            self._state.embodiment_state = EmbodimentState.REMOTE if self._state.remote_active else EmbodimentState.IDLE
            return
        self._state.embodiment_state = state
        if self._motion is not None and self._motion_token is not None:
            self._motion.conversation_state(self._motion_token, turn, state)

    async def _run(self, message: VoiceStartMessage, generation: int, send_state: SendState) -> None:
        limits = message.limits
        session_id = message.voice_session_id

        async def report(state: RobotVoiceState, detail: str | None = None) -> None:
            try:
                await send_state(VoiceStateMessage(voice_session_id=session_id, state=state, detail=detail))
            except Exception:  # noqa: BLE001 - a dead socket ends the session via on_disconnect
                log.debug("could not report voice state %s", state)

        deadline = self._clock() + limits.max_session_seconds
        turn = 1
        completed = False
        if self._motion is not None:
            self._motion_token = self._motion.begin_conversation()
        try:
            # Both can take seconds (model load; SDK media client connecting
            # to the daemon). Off the event loop, or the hub WSS keepalive
            # stalls — the hub-side version of this disconnected the robot.
            segmenter = UtteranceSegmenter(await asyncio.to_thread(self._vad_factory, limits), limits)
            microphone = await asyncio.to_thread(self._microphone_factory)
            # The hub decides per session whether it watches for a palm.
            self._palm_stop_ready = (
                message.palm_stop and self._stop_gesture is not None and await self._stop_gesture.prepare()
            )
            while True:
                try:
                    result = await self._take_turn(
                        microphone, segmenter, limits, deadline, session_id, turn, generation, report
                    )
                except MicrophoneFailed:
                    log.exception("microphone capture failed")
                    await report(RobotVoiceState.STOPPED, "Microphone unavailable")
                    return
                except VoiceSessionGone:
                    # Tell the hub in case only this turn was refused and
                    # its session is still open; ignored if it's gone.
                    await report(RobotVoiceState.STOPPED, "Hub refused the turn")
                    return
                if result is None:
                    completed = True
                    await report(RobotVoiceState.STOPPED, "Maximum conversation length reached")
                    return
                outcome, audio, cut_at = result
                turn += 1

                if outcome == VoiceTurnOutcome.SPOKEN and audio:
                    self._set_state(EmbodimentState.SPEAKING, turn - 1)
                    await report(RobotVoiceState.SPEAKING)
                    if await self._play(audio, report, session_id, turn - 1, generation):
                        log.info("voice turn %s: reply stopped by open palm", turn - 1)
                    else:
                        log.info("voice turn %s: playback done %.2fs after the cut", turn - 1, self._clock() - cut_at)
                await asyncio.sleep(limits.playback_tail_guard_ms / 1000)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("robot voice loop failed")
            await report(RobotVoiceState.STOPPED, "Robot voice loop failed")
        finally:
            self._set_state(None)
            if self._motion is not None and self._motion_token is not None:
                # Only a normal end returns home; a stop or failure holds.
                self._motion.end_conversation(self._motion_token, completed=completed)
                self._motion_token = None

    async def _take_turn(
        self,
        microphone: MicSource,
        segmenter: UtteranceSegmenter,
        limits: VoiceLimits,
        deadline: float,
        session_id: str,
        turn: int,
        generation: int,
        report: Callable[..., Awaitable[None]],
    ) -> tuple[VoiceTurnOutcome, bytes | None, float] | None:
        """One turn, possibly several segments long. Returns the hub's final
        outcome, reply audio and the last cut time, or None when the
        session's maximum length is reached. The microphone is closed on
        return, before any playback."""
        segmenter.reset()
        try:
            await asyncio.to_thread(microphone.start)
        except Exception as exc:
            raise MicrophoneFailed from exc
        capture: asyncio.Task[np.ndarray] | None = None
        try:
            self._set_state(EmbodimentState.LISTENING, turn)
            await report(RobotVoiceState.LISTENING)
            capture = asyncio.create_task(self._capture(microphone, segmenter))
            utterance = await self._await_capture(capture, segmenter, deadline)
            segment = 1
            turn_seconds = 0.0
            while utterance is not None:
                # Timing lines for latency measurement; the cut lands one
                # end-of-speech silence window after the speaker stopped.
                seconds = len(utterance) / SAMPLE_RATE
                log.info("voice turn %s.%s: utterance cut (%.2fs of audio)", turn, segment, seconds)
                cut_at = self._clock()
                turn_seconds += seconds
                remaining = limits.max_utterance_seconds - turn_seconds
                # Keep listening during the upload in case the hub holds the
                # turn; with too little budget left it won't.
                capture = None
                if limits.continuation_window_ms > 0 and remaining >= MIN_CONTINUATION_SECONDS:
                    segmenter.limit(remaining)
                    capture = asyncio.create_task(self._capture(microphone, segmenter))

                self._set_state(EmbodimentState.THINKING, turn)
                await report(RobotVoiceState.UPLOADING)
                outcome, audio = await self._send(
                    report,
                    self._uploader.post(
                        encode_wav(utterance),
                        voice_session_id=session_id,
                        turn=turn,
                        generation=generation,
                        segment=segment,
                    ),
                )
                log.info(
                    "voice turn %s.%s: hub replied %s after %.2fs",
                    turn,
                    segment,
                    outcome.value,
                    self._clock() - cut_at,
                )
                if outcome != VoiceTurnOutcome.CONTINUE:
                    return outcome, audio, cut_at

                self._set_state(EmbodimentState.LISTENING, turn)
                await report(RobotVoiceState.LISTENING)
                window_end = cut_at + limits.continuation_window_ms / 1000
                utterance = None
                if capture is not None:
                    utterance = await self._await_capture(capture, segmenter, deadline, start_by=window_end)
                if utterance is None:
                    if self._clock() >= deadline:
                        return None
                    finalized_at = self._clock()
                    outcome, audio = await self._send(
                        report,
                        self._uploader.finalize(voice_session_id=session_id, turn=turn, generation=generation),
                    )
                    log.info(
                        "voice turn %s: finalized after %s segments, hub replied %s after %.2fs",
                        turn,
                        segment,
                        outcome.value,
                        self._clock() - finalized_at,
                    )
                    return outcome, audio, cut_at
                segment += 1
            return None
        finally:
            if capture is not None and not capture.done():
                capture.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await capture
            await asyncio.to_thread(microphone.stop)

    @staticmethod
    async def _send(
        report: Callable[..., Awaitable[None]], request: Awaitable[tuple[VoiceTurnOutcome, bytes | None]]
    ) -> tuple[VoiceTurnOutcome, bytes | None]:
        try:
            return await request
        except httpx.HTTPError:
            await report(RobotVoiceState.ERROR, "Could not reach the hub")
            return VoiceTurnOutcome.FAILED, None

    async def _capture(self, microphone: MicSource, segmenter: UtteranceSegmenter) -> np.ndarray:
        while True:
            samples = await asyncio.to_thread(microphone.read)
            if samples is None or not len(samples):
                await asyncio.sleep(self._poll_interval)
                continue
            utterance = await asyncio.to_thread(segmenter.feed, samples)
            if utterance is not None:
                return utterance

    async def _await_capture(
        self,
        capture: asyncio.Task[np.ndarray],
        segmenter: UtteranceSegmenter,
        deadline: float,
        *,
        start_by: float | None = None,
    ) -> np.ndarray | None:
        """The captured utterance, or None once the session deadline passes
        or, with `start_by`, if no speech has started by then. Speech that
        started in time runs to its own end of speech."""
        while not capture.done():
            now = self._clock()
            if now >= deadline or (start_by is not None and now >= start_by and not segmenter.in_speech):
                return None
            await asyncio.sleep(self._poll_interval)
        try:
            return capture.result()
        except Exception as exc:
            raise MicrophoneFailed from exc

    async def _play(
        self, audio: bytes, report: Callable[..., Awaitable[None]], session_id: str, turn: int, generation: int
    ) -> bool:
        """Plays the reply to the end. Returns True if an open palm stopped
        it early."""
        play = asyncio.ensure_future(asyncio.to_thread(self._player.play_audio, audio))
        try:
            duration = await asyncio.shield(play)
            log.info("voice playback started (%.2fs of audio)", duration)
            if await self._palm_during(duration + PLAYBACK_MARGIN_SECONDS, session_id, turn, generation):
                log.info("open palm seen, stopping daemon audio")
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._player.stop_audio)
                return True
        except asyncio.CancelledError:
            # The daemon upload/play call can't be interrupted inside its
            # thread. Let it land first so stop_audio can't race ahead of
            # play_sound and leave the reply playing.
            with contextlib.suppress(Exception):
                await play
            log.info("voice playback cancelled, stopping daemon audio")
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._player.stop_audio)
            log.info("daemon audio stop returned")
            raise
        except Exception:
            log.exception("speaker playback failed")
            await report(RobotVoiceState.ERROR, "Speaker playback failed")
        return False

    async def _palm_during(self, seconds: float, session_id: str, turn: int, generation: int) -> bool:
        """Waits `seconds`, or less if an open palm is seen first. A
        failing watcher leaves the reply playing to its end."""
        if not self._palm_stop_ready or self._stop_gesture is None:
            await asyncio.sleep(seconds)
            return False
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        watch = asyncio.ensure_future(self._stop_gesture.wait(session_id, turn, generation))
        try:
            done, _ = await asyncio.wait({watch}, timeout=seconds)
            if watch in done:
                if watch.exception() is None:
                    return True
                log.warning("palm stop watcher failed: %s", watch.exception())
                await asyncio.sleep(max(0.0, end - loop.time()))
            return False
        finally:
            if not watch.done():
                watch.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await watch
