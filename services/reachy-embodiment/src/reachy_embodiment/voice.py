"""Robot-side conversation loop (Phase 24c, ADR 0023).

Runs only inside a session the hub started over the ADR 0019 control
socket. Each turn: open the microphone, let Silero VAD find one bounded
utterance, close the microphone, upload it to the hub with this robot's
credential, then play the reply (if the hub permitted speech) through the
daemon. Half-duplex: the microphone is closed while uploading, waiting and
speaking, plus a tail guard, so the robot cannot transcribe itself.

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
from reachy_embodiment.state import ServiceState
from shared.models.embodiment import EmbodimentState
from shared.models.robot_voice import (
    ROBOT_GENERATION_HEADER,
    SAMPLE_RATE,
    VOICE_OUTCOME_HEADER,
    VOICE_SESSION_HEADER,
    VOICE_TURN_HEADER,
    RobotVoiceState,
    VoiceLimits,
    VoiceTurnOutcome,
)
from shared.models.robot_ws import VoiceStartMessage, VoiceStateMessage
from shared.protocols.robot_ws import ROBOT_VOICE_TURN

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


class UtteranceSegmenter:
    """Turns a microphone stream into at most one utterance per listening
    phase. VAD decides where speech starts and ends; the maximum length is
    enforced here regardless of what VAD reports."""

    def __init__(self, vad: ChunkVAD, limits: VoiceLimits) -> None:
        self._vad = vad
        self._max_chunks = math.ceil(limits.max_utterance_seconds * SAMPLE_RATE / CHUNK_SAMPLES)
        self._min_samples = int(limits.min_utterance_ms * SAMPLE_RATE / 1000)
        self._preroll: deque[np.ndarray] = deque(
            maxlen=max(1, math.ceil(limits.pre_roll_ms * SAMPLE_RATE / 1000 / CHUNK_SAMPLES))
        )
        self._pending = np.empty(0, dtype=np.float32)
        self._speech: list[np.ndarray] | None = None

    def reset(self) -> None:
        self._vad.reset()
        self._preroll.clear()
        self._pending = np.empty(0, dtype=np.float32)
        self._speech = None

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

    async def post(
        self, wav_bytes: bytes, *, voice_session_id: str, turn: int, generation: int
    ) -> tuple[VoiceTurnOutcome, bytes | None]:
        response = await self._client.post(
            ROBOT_VOICE_TURN,
            content=wav_bytes,
            headers={
                "Content-Type": "audio/wav",
                "X-Robot-Id": self._robot_id,
                "Authorization": f"Bearer {self._token}",
                ROBOT_GENERATION_HEADER: str(generation),
                VOICE_SESSION_HEADER: voice_session_id,
                VOICE_TURN_HEADER: str(turn),
            },
        )
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
    ) -> None:
        self._microphone_factory = microphone_factory
        self._vad_factory = vad_factory
        self._uploader = uploader
        self._player = player
        self._state = service_state
        self._poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._session_id: str | None = None

    @property
    def voice_session_id(self) -> str | None:
        return self._session_id

    async def start(self, message: VoiceStartMessage, generation: int, send_state: SendState) -> None:
        await self.stop()
        self._session_id = message.voice_session_id
        self._task = asyncio.create_task(self._run(message, generation, send_state))

    async def stop(self, voice_session_id: str | None = None) -> None:
        if voice_session_id is not None and voice_session_id != self._session_id:
            return
        task, self._task, self._session_id = self._task, None, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def aclose(self) -> None:
        await self.stop()
        await self._uploader.aclose()

    def _set_state(self, state: EmbodimentState | None) -> None:
        if state is None:
            state = EmbodimentState.REMOTE if self._state.remote_active else EmbodimentState.IDLE
        self._state.embodiment_state = state

    async def _run(self, message: VoiceStartMessage, generation: int, send_state: SendState) -> None:
        limits = message.limits
        session_id = message.voice_session_id

        async def report(state: RobotVoiceState, detail: str | None = None) -> None:
            try:
                await send_state(VoiceStateMessage(voice_session_id=session_id, state=state, detail=detail))
            except Exception:  # noqa: BLE001 - a dead socket ends the session via on_disconnect
                log.debug("could not report voice state %s", state)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + limits.max_session_seconds
        turn = 1
        try:
            # Both can take seconds (model load; SDK media client connecting
            # to the daemon). Off the event loop, or the hub WSS keepalive
            # stalls — the hub-side version of this disconnected the robot.
            segmenter = UtteranceSegmenter(await asyncio.to_thread(self._vad_factory, limits), limits)
            microphone = await asyncio.to_thread(self._microphone_factory)
            while True:
                try:
                    utterance = await self._listen(microphone, segmenter, deadline, report)
                except Exception:
                    log.exception("microphone capture failed")
                    await report(RobotVoiceState.STOPPED, "Microphone unavailable")
                    return
                if utterance is None:
                    await report(RobotVoiceState.STOPPED, "Maximum conversation length reached")
                    return

                self._set_state(EmbodimentState.THINKING)
                await report(RobotVoiceState.UPLOADING)
                try:
                    outcome, audio = await self._uploader.post(
                        encode_wav(utterance), voice_session_id=session_id, turn=turn, generation=generation
                    )
                except VoiceSessionGone:
                    # Tell the hub in case only this turn was refused and
                    # its session is still open; ignored if it's gone.
                    await report(RobotVoiceState.STOPPED, "Hub refused the turn")
                    return
                except httpx.HTTPError:
                    await report(RobotVoiceState.ERROR, "Could not reach the hub")
                    outcome, audio = VoiceTurnOutcome.FAILED, None
                turn += 1

                if outcome == VoiceTurnOutcome.SPOKEN and audio:
                    self._set_state(EmbodimentState.SPEAKING)
                    await report(RobotVoiceState.SPEAKING)
                    await self._play(audio, report)
                await asyncio.sleep(limits.playback_tail_guard_ms / 1000)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("robot voice loop failed")
            await report(RobotVoiceState.STOPPED, "Robot voice loop failed")
        finally:
            self._set_state(None)

    async def _listen(
        self,
        microphone: MicSource,
        segmenter: UtteranceSegmenter,
        deadline: float,
        report: Callable[[RobotVoiceState], Awaitable[None]],
    ) -> np.ndarray | None:
        loop = asyncio.get_running_loop()
        segmenter.reset()
        await asyncio.to_thread(microphone.start)
        try:
            self._set_state(EmbodimentState.LISTENING)
            await report(RobotVoiceState.LISTENING)
            while loop.time() < deadline:
                samples = await asyncio.to_thread(microphone.read)
                if samples is None or not len(samples):
                    await asyncio.sleep(self._poll_interval)
                    continue
                utterance = await asyncio.to_thread(segmenter.feed, samples)
                if utterance is not None:
                    return utterance
            return None
        finally:
            await asyncio.to_thread(microphone.stop)

    async def _play(self, audio: bytes, report: Callable[..., Awaitable[None]]) -> None:
        play = asyncio.ensure_future(asyncio.to_thread(self._player.play_audio, audio))
        try:
            duration = await asyncio.shield(play)
            await asyncio.sleep(duration + PLAYBACK_MARGIN_SECONDS)
        except asyncio.CancelledError:
            # The daemon upload/play call can't be interrupted inside its
            # thread. Let it land first so stop_audio can't race ahead of
            # play_sound and leave the reply playing.
            with contextlib.suppress(Exception):
                await play
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._player.stop_audio)
            raise
        except Exception:
            log.exception("speaker playback failed")
            await report(RobotVoiceState.ERROR, "Speaker playback failed")
