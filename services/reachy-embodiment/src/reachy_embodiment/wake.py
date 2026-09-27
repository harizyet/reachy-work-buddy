"""Robot-side wake monitoring (Phase 24g, ADR 0023 wake-started sessions).

Runs only while the hub has armed this robot over the control socket, no
voice session is running and the daemon is up. The microphone feeds a local
keyword detector; audio stays in a short ring buffer that is continuously
overwritten. A detection starts a candidate: the robot lifts its head to
the silent alert pose (with the `wake_animation` switch on), a cue to go
on speaking; an admitted conversation brings it home, and anything else
lowers it back to sleep. It captures the wake phrase
from the ring buffer together with the request that follows it. When the
first segment is too short to hold more than the phrase, the robot waits
up to `speech_start_seconds` for the request; silence discards the
candidate here, and nothing is uploaded.

A candidate that passes is primed on the conversation and uploaded to the
hub, which transcribes it in memory and either rejects it (the robot goes
back to listening) or opens a session and sends `voice_start`. The robot
control client suspends monitoring before any session starts, so the
microphone is released first; the conversation's `on_idle` resumes it, and
the robot goes back to its sleep pose.

Nothing here keeps or logs audio or text; log lines carry scores and
outcomes only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from typing import Protocol

import httpx
import numpy as np

from reachy_embodiment.motion import MotionController, RestPose
from reachy_embodiment.voice import (
    ChunkVAD,
    MicSource,
    UtteranceSegmenter,
    VoiceConversation,
    VoiceSessionGone,
    encode_wav,
    start_microphone,
)
from shared.models.robot_voice import SAMPLE_RATE, VoiceLimits, WakeLimits
from shared.models.robot_ws import WakeArmMessage

log = logging.getLogger(__name__)

# Label the community "Hey Reachy" model scores (docs/verification/
# phase-24g-detector-bench-2026-09-27.md).
WAKE_LABEL = "hey_reachy"
# Audio kept before a detection beyond the detector's own window, so the
# whole phrase is in the candidate even when it straddled a step.
EXTRA_RING_SECONDS = 0.5


class WakeDetector(Protocol):
    window_seconds: float

    def score(self, samples: np.ndarray) -> float:
        """Wake score for exactly `window_seconds` of mono float32 16 kHz."""
        ...

    def close(self) -> None: ...


class WakeCandidateUploader(Protocol):
    async def wake_candidate(self, wav_bytes: bytes, *, arm_id: str, generation: int) -> str | None: ...


class EdgeImpulseWakeDetector:
    """An Edge Impulse `.eim` keyword model: a native runner process driven
    over a Unix socket with JSON requests, each response ending in a NUL
    byte (the protocol of Edge Impulse's own Linux SDK, whose Python package
    needs pyaudio). The model's rate differs from the microphone's, so each
    window is linearly interpolated to it."""

    def __init__(self, model_path: str, *, label: str = WAKE_LABEL, start_timeout: float = 10.0) -> None:
        self._label = label
        self._dir = tempfile.mkdtemp(prefix="wake-")
        socket_path = os.path.join(self._dir, "runner.sock")
        self._proc = subprocess.Popen(
            [model_path, socket_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._sock: socket.socket | None = None
        self._id = 0
        try:
            deadline = time.monotonic() + start_timeout
            while not os.path.exists(socket_path):
                if self._proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"wake model runner did not start ({self._proc.poll()})")
                time.sleep(0.05)
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(socket_path)
            params = self._send({"hello": 1})["model_parameters"]
            if label not in params["labels"]:
                raise RuntimeError(f"wake model has no {label!r} label")
            self._samples = int(params["input_features_count"])
            self.window_seconds = self._samples / float(params["frequency"])
        except Exception:
            self.close()
            raise

    def _send(self, message: dict) -> dict:
        assert self._sock is not None
        self._id += 1
        message["id"] = self._id
        self._sock.sendall(json.dumps(message).encode())
        data = b""
        while not data.endswith(b"\0"):
            chunk = self._sock.recv(65536)
            if not chunk:
                raise RuntimeError("wake model runner closed its socket")
            data += chunk
        response = json.loads(data[:-1])
        if not response.get("success"):
            raise RuntimeError(f"wake model runner error: {response.get('error')}")
        return response

    def score(self, samples: np.ndarray) -> float:
        positions = np.linspace(0, len(samples) - 1, self._samples)
        resampled = np.interp(positions, np.arange(len(samples)), samples)
        features = np.clip(np.round(resampled * 32767), -32768, 32767).astype(int).tolist()
        result = self._send({"classify": features})["result"]
        return float(result["classification"].get(self._label, 0.0))

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        shutil.rmtree(self._dir, ignore_errors=True)


class WakeMonitor:
    def __init__(
        self,
        microphone_factory: Callable[[], MicSource],
        detector_factory: Callable[[], WakeDetector],
        vad_factory: Callable[[VoiceLimits], ChunkVAD],
        uploader: WakeCandidateUploader,
        conversation: VoiceConversation,
        *,
        motion: MotionController | None = None,
        daemon_ready: Callable[[], bool] | None = None,
        poll_interval: float = 0.01,
        idle_interval: float = 0.2,
        ready_interval: float = 5.0,
        admission_wait: float = 5.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._microphone_factory = microphone_factory
        self._detector_factory = detector_factory
        self._vad_factory = vad_factory
        self._uploader = uploader
        self._conversation = conversation
        self._motion = motion
        self._daemon_ready = daemon_ready
        self._poll_interval = poll_interval
        self._idle_interval = idle_interval
        self._ready_interval = ready_interval
        self._admission_wait = admission_wait
        self._clock = clock or (lambda: asyncio.get_running_loop().time())
        self._arm: WakeArmMessage | None = None
        self._generation: int | None = None
        self._task: asyncio.Task[None] | None = None
        self._detector: WakeDetector | None = None
        # Whether the robot is already in its sleep pose; any wake-up or
        # conversation clears it, so the next listening phase rests again.
        self._resting = False
        self._motion_task: asyncio.Future[bool] | None = None
        # True from a candidate's upload until its session starts or it is
        # turned down.
        self._submitting = False
        self._ready_at: float | None = None
        self._ready = False

    @property
    def armed(self) -> bool:
        return self._arm is not None

    @property
    def listening(self) -> bool:
        return self._task is not None and not self._task.done()

    async def arm(self, message: WakeArmMessage, generation: int) -> None:
        if message.arm_id is None:
            await self.disarm()
            return
        if self._arm is not None and self._arm.arm_id == message.arm_id and self._generation == generation:
            return
        await self._cancel()
        log.info("wake listening armed")
        self._arm, self._generation = message, generation
        self.resume()

    async def disarm(self) -> None:
        if self._arm is not None:
            log.info("wake listening disarmed")
        self._arm = self._generation = None
        await self._cancel()

    async def suspend(self) -> None:
        """Releases the microphone before a voice session starts. The hub
        opens an admitted candidate's session before it answers the upload,
        so a suspend during the upload is the admission."""
        admitted = self._submitting
        self._resting = False
        await self._cancel()
        if admitted:
            log.info("wake candidate admitted")
            await self._rest_move("home")

    def resume(self) -> None:
        """Monitoring again, if armed; the conversation calls this when it
        goes idle."""
        if self._arm is None or self._generation is None or self.listening:
            return
        self._task = asyncio.create_task(self._run(self._arm, self._generation))

    async def aclose(self) -> None:
        await self.disarm()
        if self._motion_task is not None:
            with contextlib.suppress(Exception):
                await self._motion_task
        if self._detector is not None:
            await asyncio.to_thread(self._detector.close)
            self._detector = None

    async def _cancel(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self, arm: WakeArmMessage, generation: int) -> None:
        assert arm.arm_id is not None
        limits = arm.limits
        try:
            if self._detector is None:
                self._detector = await asyncio.to_thread(self._detector_factory)
            candidate_limits = VoiceLimits(max_utterance_seconds=limits.max_candidate_seconds)
            vad = await asyncio.to_thread(self._vad_factory, candidate_limits)
            microphone = await asyncio.to_thread(self._microphone_factory)
            while True:
                await self._wait_until_free()
                if not self._resting:
                    await self._rest_move("sleep")
                    self._resting = True
                candidate = await self._listen_and_capture(microphone, self._detector, vad, limits)
                if candidate is None:
                    continue
                if await self._submit(candidate, arm.arm_id, generation) is None:
                    return  # the arm or connection is stale; wait for a new arm
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("wake monitoring failed; waiting for the hub to arm it again")

    async def _wait_until_free(self) -> None:
        while self._conversation.voice_session_id is not None or not await self._daemon_up():
            self._resting = False
            await asyncio.sleep(self._idle_interval)

    async def _daemon_up(self) -> bool:
        """The daemon's state, checked at most every `ready_interval`."""
        if self._daemon_ready is None:
            return True
        now = self._clock()
        if self._ready_at is None or now - self._ready_at >= self._ready_interval:
            self._ready = await asyncio.to_thread(self._daemon_ready)
            self._ready_at = now
        return self._ready

    async def _rest_move(self, pose: RestPose) -> None:
        """Waits for the sleep move; the alert and home cues run alongside
        capture and the conversation's start."""
        if self._motion is None:
            return
        previous = self._motion_task
        if previous is not None:
            with contextlib.suppress(Exception):
                await previous
        move = asyncio.ensure_future(asyncio.to_thread(self._motion.rest_move, pose))
        self._motion_task = move
        if pose == "sleep":
            with contextlib.suppress(Exception):
                await move

    async def _listen_and_capture(
        self, microphone: MicSource, detector: WakeDetector, vad: ChunkVAD, limits: WakeLimits
    ) -> np.ndarray | None:
        """One listening phase: the captured candidate, or None when it was
        discarded here or monitoring should pause. The microphone is closed
        on return, before anything is uploaded."""
        await start_microphone(microphone)
        try:
            ring = await self._listen(microphone, detector, limits)
            if ring is None:
                return None
            self._resting = False
            await self._rest_move("alert")
            candidate = await self._capture_candidate(microphone, ring, vad, limits)
            if candidate is None:
                log.info("wake candidate discarded on the robot: no request followed")
            return candidate
        finally:
            await asyncio.to_thread(microphone.stop)

    async def _listen(self, microphone: MicSource, detector: WakeDetector, limits: WakeLimits) -> np.ndarray | None:
        window = round(detector.window_seconds * SAMPLE_RATE)
        step = max(1, window // 4)  # as the Edge Impulse SDK steps its audio windows
        ring = np.empty(0, dtype=np.float32)
        keep = window + round(EXTRA_RING_SECONDS * SAMPLE_RATE)
        since_step = 0
        while True:
            if self._conversation.voice_session_id is not None or not await self._daemon_up():
                return None
            samples = await asyncio.to_thread(microphone.read)
            if samples is None or not len(samples):
                await asyncio.sleep(self._poll_interval)
                continue
            ring = np.concatenate([ring, samples.astype(np.float32, copy=False)])[-keep:]
            since_step += len(samples)
            if since_step < step or len(ring) < window:
                continue
            since_step = 0
            score = await asyncio.to_thread(detector.score, ring[-window:])
            if score >= limits.detection_threshold:
                log.info("wake phrase detected (score %.2f)", score)
                return ring

    async def _capture_candidate(
        self, microphone: MicSource, ring: np.ndarray, vad: ChunkVAD, limits: WakeLimits
    ) -> np.ndarray | None:
        segment_limits = VoiceLimits(max_utterance_seconds=limits.max_candidate_seconds)
        segmenter = UtteranceSegmenter(vad, segment_limits)
        segmenter.reset()
        # A segment carries the pre-roll before speech and the end-of-speech
        # silence after it; "Hey Reachy" alone is about a second of each
        # plus under a second of speech.
        padding = (segment_limits.pre_roll_ms + segment_limits.end_of_speech_silence_ms) / 1000
        deadline = self._clock() + limits.max_candidate_seconds
        first = await asyncio.to_thread(segmenter.feed, ring)
        if first is None:
            first = await self._segment(microphone, segmenter, self._clock() + limits.speech_start_seconds, deadline)
        if first is None:
            return None
        parts = [first]
        if len(first) / SAMPLE_RATE - padding < limits.min_request_seconds:
            # Only the phrase so far: a natural pause before the request.
            segmenter.limit(max(0.1, limits.max_candidate_seconds - len(first) / SAMPLE_RATE))
            second = await self._segment(
                microphone, segmenter, self._clock() + limits.speech_start_seconds, deadline
            )
            if second is None:
                return None
            parts.append(second)
        return np.concatenate(parts)[: round(limits.max_candidate_seconds * SAMPLE_RATE)]

    async def _segment(
        self, microphone: MicSource, segmenter: UtteranceSegmenter, start_by: float, deadline: float
    ) -> np.ndarray | None:
        """The next segment, or None if no speech starts by `start_by`.
        Speech that started runs to its end, capped by the segmenter."""
        while True:
            now = self._clock()
            if not segmenter.in_speech and (now >= start_by or now >= deadline):
                return None
            samples = await asyncio.to_thread(microphone.read)
            if samples is None or not len(samples):
                await asyncio.sleep(self._poll_interval)
                continue
            utterance = await asyncio.to_thread(segmenter.feed, samples)
            if utterance is not None:
                return utterance

    async def _submit(self, candidate: np.ndarray, arm_id: str, generation: int) -> bool | None:
        """Uploads the candidate. True when a session was admitted, False
        when it was rejected or could not be sent, None when the arm is
        stale."""
        self._conversation.prime(candidate)
        self._submitting = True
        try:
            try:
                session_id = await self._uploader.wake_candidate(
                    encode_wav(candidate), arm_id=arm_id, generation=generation
                )
            except VoiceSessionGone as exc:
                self._conversation.prime(None)
                log.warning("wake candidate refused (%s); monitoring pauses until re-armed", exc)
                return None
            except httpx.HTTPError as exc:
                self._conversation.prime(None)
                log.warning("wake candidate upload failed: %s", exc)
                return False
            if session_id is None:
                self._conversation.prime(None)
                log.info("wake candidate rejected by the hub")
                return False
            # Normally voice_start has already suspended this task (see
            # `suspend`). If it never arrives, drop the candidate and listen
            # again.
            waited_until = self._clock() + self._admission_wait
            while self._conversation.voice_session_id != session_id and self._clock() < waited_until:
                await asyncio.sleep(self._idle_interval)
        finally:
            self._submitting = False
        if self._conversation.voice_session_id != session_id:
            self._conversation.prime(None)
            log.warning("admitted wake session never started; listening again")
        return True
