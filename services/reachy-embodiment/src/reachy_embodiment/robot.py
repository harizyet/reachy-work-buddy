"""Robot backend abstraction.

Phase 2 only needed the semantic HTTP layer to prove it can drive
*something* named after a behaviour; it did not need real Reachy hardware.
This mirrors Jarvis's own RobotController, which exposes a `sim` property
precisely so the rest of the stack doesn't care whether hardware is
attached (see docs/jarvis-baseline.md, robot/controller.py section).

Phase 22 adds `ReachyDaemonBackend`, a real implementation talking to
`reachy-mini-daemon` over HTTP (see docs/verification/phase-22-inventory-
2026-09-22.md's "Nano-role recommendation" and daemon API sections for why
it's an HTTP client rather than an in-process `reachy_mini` SDK import: the
SDK class itself is just a thin HTTP/WS client to the daemon, which is the
process that actually owns the serial/camera/audio hardware). It plugs in
behind the same RobotBackend protocol as SimulatedRobotBackend, so nothing
above this module changes. Phase 22b's `capture_frame` (below) is the one
deliberate exception to the "no in-process SDK" rule above: reading camera
frames from the daemon's local media socket is the SDK's own documented
same-host path, not a movement/control command, so it doesn't reopen the
question of who owns motor/serial control.

**`ReachyDaemonBackend` is only partly verified against a live daemon.**
Named moves were confirmed live in Phase 22b. Standby/resume, audio
upload/play/stop and microphone capture are best-effort reads of the pinned
daemon source, not confirmed live responses. Treat every "unverified" note
below as a real gap to close before trusting this in production, not hedging.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlsplit

import httpx
import numpy as np
from PIL import Image, ImageDraw

from shared.models.embodiment import Behaviour

log = logging.getLogger(__name__)

_FRAME_SIZE = (320, 240)


def wav_duration(wav_bytes: bytes) -> float:
    """Seconds of audio actually present. Counts the PCM bytes rather than
    trusting the header's frame count, which streaming writers (espeak-ng
    --stdout) fill with a placeholder — see reachy_hub/tts.py."""
    with io.BytesIO(wav_bytes) as buf, wave.open(buf, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        bytes_per_second = wf.getframerate() * wf.getnchannels() * wf.getsampwidth()
    return len(frames) / bytes_per_second


class MicSource(Protocol):
    """See reachy_embodiment.voice.MicSource (duplicated structurally so
    this module stays importable without the voice loop)."""

    def start(self) -> None: ...

    def read(self) -> np.ndarray | None: ...

    def stop(self) -> None: ...


class RobotBackend(Protocol):
    @property
    def connected(self) -> bool: ...

    @property
    def sim(self) -> bool: ...

    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None: ...

    def stop_motion(self) -> None:
        """Stops the move this backend last started, if any. Phase 24f."""
        ...

    def goto_home(self) -> None:
        """One bounded move to IDLE_HOME, the daemon's own wake-up end pose.
        Phase 24f; only the motion controller calls it."""
        ...

    def set_speech_wobble(self, enabled: bool) -> None:
        """Switches the daemon's audio-reactive head motion. Phase 24f."""
        ...

    def capture_frame(self, max_width: int | None = None) -> bytes:
        """Returns a single JPEG-encoded camera frame. Phase 16/ADR 0013.
        `max_width` downscales before encoding (Phase 24e palm-stop frames)."""
        ...

    def play_audio(self, wav_bytes: bytes) -> float:
        """Plays 16-bit PCM WAV bytes through the robot's speaker, returns
        the audio's duration in seconds. Phase 16/ADR 0013."""
        ...

    def stop_audio(self) -> None:
        """Stops whatever `play_audio` started. Phase 24c: conversation
        cancellation must silence the speaker, not just drop HTTP work."""
        ...

    def open_microphone(self) -> MicSource:
        """Returns this robot's microphone as mono float32 16 kHz samples.
        Opening it does not start capture; `MicSource.start` does."""
        ...

    def daemon_standby(self) -> dict[str, object]:
        """Parks the robot at its rest pose and de-torques motors, safe to
        physically handle afterwards. Phase 22b: owner-requested remote
        "turn off/standby" command. Returns the resulting daemon status
        (not just "command sent") so a caller can report real state."""
        ...

    def daemon_resume(self, *, wake_up: bool = True) -> dict[str, object]:
        """Resumes a backend previously put into standby. `wake_up=True`
        (default) replays the daemon's own wake-up motion, matching a
        normal daemon start. Returns the resulting daemon status."""
        ...

    def close(self) -> None:
        """Releases any resources opened lazily (e.g. Phase 22b's camera
        media client). Called once from the app's shutdown lifespan; safe
        to call even if nothing was ever opened."""
        ...


class SimulatedRobotBackend:
    """Logs behaviour triggers instead of driving hardware."""

    def __init__(self) -> None:
        self._connected = True

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def sim(self) -> bool:
        return True

    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None:
        log.info("sim: playing behaviour %s params=%s", name.value, parameters)

    def stop_motion(self) -> None:
        log.info("sim: stop motion")

    def goto_home(self) -> None:
        log.info("sim: goto home")

    def set_speech_wobble(self, enabled: bool) -> None:
        log.info("sim: speech wobble %s", "on" if enabled else "off")

    def capture_frame(self, max_width: int | None = None) -> bytes:
        # No physical camera exists in this environment. The marker's
        # position is derived from wall-clock time so consecutive polls
        # visibly differ — proof a live transport is delivering fresh
        # frames, not a cached static image, the same purpose
        # play_behaviour's log line serves for motion.
        width, height = _FRAME_SIZE
        if max_width is not None and width > max_width:
            width, height = max_width, round(height * max_width / width)
        image = Image.new("RGB", (width, height), color=(20, 24, 32))
        draw = ImageDraw.Draw(image)
        x = int((time.monotonic() % 2.0) / 2.0 * (width - 12))
        draw.rectangle([x, 0, x + 12, height], fill=(91, 140, 255))
        draw.text((8, 8), "SIMULATED CAMERA", fill=(238, 238, 238))
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=70)
        return buf.getvalue()

    def play_audio(self, wav_bytes: bytes) -> float:
        duration = wav_duration(wav_bytes)
        log.info("sim: playing %.2fs of audio (no physical speaker in this environment)", duration)
        return duration

    def stop_audio(self) -> None:
        log.info("sim: stop audio")

    def open_microphone(self) -> MicSource:
        return SimulatedMicSource.from_env()

    def daemon_standby(self) -> dict[str, object]:
        log.info("sim: daemon standby (no physical daemon in this environment)")
        self._connected = False
        return {"state": "stopped", "simulation_enabled": True}

    def daemon_resume(self, *, wake_up: bool = True) -> dict[str, object]:
        log.info("sim: daemon resume wake_up=%s (no physical daemon in this environment)", wake_up)
        self._connected = True
        return {"state": "running", "simulation_enabled": True}

    def close(self) -> None:
        pass


class SimulatedMicSource:
    """Phase 24c simulation fixture, not a microphone. Each `start()` (one
    per listening phase) takes the next queued WAV and emits it in real
    time after a short lead-in of silence, then silence until stopped, so
    a simulated robot can hold a multi-turn conversation through the real
    upload/STT/LLM/TTS path. `SIM_MIC_WAVS` lists 16 kHz mono 16-bit WAV
    paths separated by os.pathsep; unset means silence only.
    """

    LEAD_IN_SECONDS = 0.3

    def __init__(self, utterances: list[np.ndarray] | None = None, *, clock: Callable[[], float] = time.monotonic):
        self._queue: deque[np.ndarray] = deque(utterances or [])
        self._clock = clock
        self._current: np.ndarray | None = None
        self._started_at: float | None = None
        self._emitted = 0

    @classmethod
    def from_env(cls) -> SimulatedMicSource:
        paths = [p for p in os.environ.get("SIM_MIC_WAVS", "").split(os.pathsep) if p]
        utterances = []
        for path in paths:
            with wave.open(path, "rb") as wf:
                if wf.getframerate() != 16000 or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                    raise ValueError(f"{path}: SIM_MIC_WAVS entries must be 16 kHz mono 16-bit WAV")
                raw = wf.readframes(wf.getnframes())
            utterances.append(np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0)
        return cls(utterances)

    def start(self) -> None:
        lead_in = np.zeros(int(self.LEAD_IN_SECONDS * 16000), dtype=np.float32)
        self._current = np.concatenate([lead_in, self._queue.popleft()]) if self._queue else lead_in
        self._started_at = self._clock()
        self._emitted = 0

    def read(self) -> np.ndarray | None:
        if self._started_at is None:
            return None
        due = int((self._clock() - self._started_at) * 16000)
        if due <= self._emitted:
            return None
        out = np.zeros(due - self._emitted, dtype=np.float32)
        assert self._current is not None
        available = self._current[self._emitted : due]
        out[: len(available)] = available
        self._emitted = due
        return out

    def stop(self) -> None:
        self._started_at = None
        self._current = None


class ReachyMiniMicSource:
    """The robot microphone through the `reachy_mini` SDK's LOCAL audio
    backend, which opens the ALSA `reachymini_audio_src` dsnoop device the
    daemon also uses (see docs/deployment.md#robot-voice-conversation for
    the container requirements). The SDK delivers stereo float32 at 16 kHz;
    both channels are averaged to mono. UNVERIFIED on the Nano: channel
    layout and dsnoop sharing from the container have not been exercised.
    """

    def __init__(self, media: object) -> None:
        self._media = media

    def start(self) -> None:
        self._media.start_recording()  # type: ignore[attr-defined]

    def read(self) -> np.ndarray | None:
        # Blocks for at most ~20 ms (the SDK's appsink pull timeout).
        sample = self._media.get_audio_sample()  # type: ignore[attr-defined]
        if sample is None:
            return None
        return sample.mean(axis=1).astype(np.float32) if sample.ndim == 2 else sample.astype(np.float32)

    def stop(self) -> None:
        self._media.stop_recording()  # type: ignore[attr-defined]


class RobotBackendError(RuntimeError):
    """A real-hardware backend call failed in a way callers should see,
    not silently swallow. Per Phase 22's plan: real mode must fail clearly
    rather than silently behave like simulation."""


# Default move-dataset/name mapping for POST /move/play/recorded-move-
# dataset/{dataset}/{move_name}. VERIFIED against the real daemon's
# actual bundled datasets during Phase 22 live hardware testing on the
# Jetson Nano — the daemon preloads exactly two, and there is no
# "default" dataset (an earlier version of this mapping guessed one,
# wrongly; every behaviour would have 404'd). Move names below were
# enumerated directly from the real HuggingFace dataset contents
# (`RecordedMoves("pollen-robotics/...")`), not guessed from Behaviour's
# own string values — only `waiting` happens to be an exact string match.
#
# Deliberately incomplete: the continuous idle-loop behaviours
# (idle_breathing, subtle_scan, antenna_twitch, driven by presence.py's
# ~3s cycle) have no real match in either dataset — both are one-shot
# emotive/dance animations, not a breathing-style loop — so they're left
# unmapped rather than forced onto a misleading "closest available"
# move; play_behaviour() already logs and no-ops for an unmapped
# behaviour, the same safe fallback an unrecognized move name gets.
# goodbye/sent_to_phone/meeting_soon are similarly left unmapped — no
# real move in either dataset fits them either. speaking is intentionally
# unmapped too: POST /audio/play's real playback works independently of
# any behaviour-triggered move.
#
# Override via ReachyDaemonBackend(behaviour_moves=...) for a different
# mapping (e.g. once a project-specific recorded-move dataset exists).
_EMOTIONS_DATASET = "pollen-robotics/reachy-mini-emotions-library"
_DANCES_DATASET = "pollen-robotics/reachy-mini-dances-library"

_DEFAULT_BEHAVIOUR_MOVES: dict[Behaviour, tuple[str, str]] = {
    Behaviour.LISTENING: (_EMOTIONS_DATASET, "attentive1"),
    Behaviour.THINKING: (_EMOTIONS_DATASET, "thoughtful1"),
    Behaviour.ACKNOWLEDGEMENT: (_EMOTIONS_DATASET, "yes1"),
    Behaviour.UNDERSTOOD: (_EMOTIONS_DATASET, "understanding1"),
    Behaviour.UNCERTAIN: (_EMOTIONS_DATASET, "uncertain1"),
    Behaviour.GREETING: (_EMOTIONS_DATASET, "welcoming1"),
    Behaviour.WAITING: (_EMOTIONS_DATASET, "waiting"),
    Behaviour.TASK_COMPLETE: (_EMOTIONS_DATASET, "success1"),
    Behaviour.CANNOT_COMPLY: (_EMOTIONS_DATASET, "no_sad1"),
    Behaviour.INCOMING_MESSAGE: (_EMOTIONS_DATASET, "surprised1"),
    Behaviour.IMPORTANT_NOTICE: (_EMOTIONS_DATASET, "surprised2"),
    Behaviour.DO_NOT_DISTURB: (_EMOTIONS_DATASET, "serenity1"),
    Behaviour.SLEEP: (_EMOTIONS_DATASET, "sleep1"),
    Behaviour.WAKE: (_EMOTIONS_DATASET, "wake-mini-up"),
}


# IDLE_HOME: reachy-mini 1.8.4's wake-up end pose (INIT_HEAD_POSE identity,
# INIT_ANTENNAS_JOINT_POSITIONS [right, left] in rad) with body yaw 0 sent
# explicitly, since REST keeps the current yaw when it is omitted. Built
# from fixed keys: a misspelled pose key validates as identity in 1.8.4
# (docs/verification/phase-24f-source-2026-09-25.md).
HOME_GOTO: dict[str, object] = {
    "head_pose": {"x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0},
    "antennas": [-0.1745, 0.1745],
    "body_yaw": 0.0,
    "duration": 1.0,
}


class ReachyDaemonBackend:
    """Drives a real Reachy Mini via `reachy-mini-daemon`'s HTTP API.

    Intended to run alongside the daemon on the same host (the Jetson
    Nano, per Phase 22's inventory), talking to it over localhost — the
    daemon's own `--fastapi-host` defaults to 127.0.0.1 and Phase 22's
    architecture doesn't call for reaching it over the network. See this
    module's docstring for why this is an HTTP client rather than an
    in-process SDK import, and for the "first draft, unverified" caveat
    that applies to every method below.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        command_timeout: float = 5.0,
        status_timeout: float = 1.5,
        behaviour_moves: dict[Behaviour, tuple[str, str]] | None = None,
        transport: httpx.BaseTransport | None = None,
        media_client_factory: Callable[[], object] | None = None,
    ) -> None:
        # Every reachy-mini-daemon route lives under /api (e.g. /api/daemon/status,
        # /api/move/play/...) — confirmed live against the real daemon's own
        # /openapi.json during Phase 22 Nano hardware testing; not visible
        # from reading the router source alone (each APIRouter's own
        # sub-prefix, like "/move", doesn't show the top-level /api mount
        # applied when the daemon assembles its FastAPI app). Every path
        # below this point is written as if /api/ already, verified to
        # actually resolve correctly by httpx (it keeps this base path
        # regardless of whether the request path starts with "/").
        #
        # `transport` is exposed purely so tests can inject an
        # httpx.MockTransport while still going through this real
        # base_url-with-/api construction, rather than swapping `_client`
        # after the fact and silently losing prefix coverage.
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/api", timeout=command_timeout, transport=transport
        )
        self._status_timeout = status_timeout
        self._behaviour_moves = behaviour_moves if behaviour_moves is not None else dict(_DEFAULT_BEHAVIOUR_MOVES)
        # Daemon UUID of the last move this backend started. reachy-mini
        # 1.8.4's single-move guard is a re-entrant lock on one event-loop
        # thread, so overlapping REST moves both run and fight at 100 Hz
        # (docs/verification/phase-24f-source-2026-09-25.md). We stop our
        # own previous move before starting another. `_move_lock` makes
        # stop-then-start atomic across the presence thread and FastAPI's
        # threadpool.
        self._active_move_uuid: str | None = None
        self._move_lock = threading.Lock()
        # Phase 22b camera refactor: lazily created, then kept alive for the
        # process lifetime (never used as a context manager during normal
        # operation, so its __exit__ never fires and never calls
        # release_media/acquire_media on the daemon — only `close()` calls
        # it, once, at shutdown). `media_client_factory` lets tests
        # substitute a fake without a real `reachy_mini` import. `_mini_lock`
        # guards the lazy-init check-then-create below: FastAPI runs sync
        # routes (like GET /camera/frame) in a thread pool, so two requests
        # racing right after startup could otherwise both see `_mini is
        # None` and construct two separate ReachyMini clients against the
        # same daemon socket.
        self._media_client_factory = media_client_factory
        self._mini: object | None = None
        self._mini_lock = threading.Lock()
        # ReachyMini defaults to `host="reachy-mini.local"` (mDNS), which
        # this container has no reason to be able to resolve. Derive the
        # actual daemon host/port from the same base_url used for the HTTP
        # client above, and pass connection_mode="localhost_only" so it
        # never attempts network/mDNS discovery — reachy-embodiment and the
        # daemon are documented to always run on the same host (see this
        # class's docstring).
        parsed = urlsplit(base_url)
        self._daemon_host = parsed.hostname or "127.0.0.1"
        self._daemon_port = parsed.port or 8000

    def _fetch_status(self) -> dict | None:
        try:
            resp = self._client.get("/daemon/status", timeout=self._status_timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            log.warning("reachy-mini-daemon status check failed: %s", exc)
            return None

    @property
    def connected(self) -> bool:
        status = self._fetch_status()
        if status is None or status.get("error"):
            return False
        # A daemon put into standby (POST /daemon/stop) keeps its HTTP
        # server up and answers /daemon/status without an `error`, but its
        # backend/motor control loop is stopped and motors are de-torqued
        # — not "connected" in any sense a caller (presence loop,
        # trigger_gesture) should act on. Phase 22b: found while adding
        # daemon_standby/daemon_resume; UNVERIFIED exact state string
        # against a live standby response, inferred from the daemon's own
        # "Daemon stopped successfully." log line.
        state = str(status.get("state", "")).lower()
        return state not in ("stopped", "stopping")

    @property
    def sim(self) -> bool:
        status = self._fetch_status()
        if status is None:
            # Can't confirm the daemon's own mode; don't claim real
            # hardware is active when we genuinely don't know.
            return True
        return bool(status.get("simulation_enabled")) or bool(status.get("mockup_sim_enabled"))

    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None:
        mapping = self._behaviour_moves.get(name)
        if mapping is None:
            log.warning("no move mapping for behaviour %s, skipping", name.value)
            return
        dataset, move_name = mapping
        with self._move_lock:
            self._stop_active_move_locked()
            try:
                resp = self._client.post(f"/move/play/recorded-move-dataset/{dataset}/{move_name}")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                # Deliberately not raised: a missing/misnamed move shouldn't
                # take down the whole /behaviour/{name} request, the same way
                # an unmapped behaviour above just logs and no-ops. Real
                # command failures worth surfacing loudly (daemon unreachable
                # entirely) are still visible via `connected` going False.
                log.warning("play_behaviour(%s) -> %s/%s failed: %s", name.value, dataset, move_name, exc)
                return
            self._remember_move_locked(resp, name.value)

    def _remember_move_locked(self, resp: httpx.Response, what: str) -> None:
        try:
            self._active_move_uuid = str(resp.json()["uuid"])
        except (ValueError, KeyError, TypeError):
            log.warning("%s: daemon response had no move uuid; cannot stop it later", what)

    def stop_motion(self) -> None:
        with self._move_lock:
            self._stop_active_move_locked()

    def goto_home(self) -> None:
        """POST /move/goto with HOME_GOTO, after stopping our previous move.
        REST ignores `interpolation` (always min-jerk), so none is sent.
        Failures are logged like play_behaviour's."""
        with self._move_lock:
            self._stop_active_move_locked()
            try:
                resp = self._client.post("/move/goto", json=HOME_GOTO)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("goto_home failed: %s", exc)
                return
            self._remember_move_locked(resp, "goto_home")

    def set_speech_wobble(self, enabled: bool) -> None:
        """POST /media/wobbling/enable or /disable. Disable also zeroes the
        offsets. It is a daemon-wide setting: while on, the daemon's own
        sounds wobble too."""
        path = "/media/wobbling/enable" if enabled else "/media/wobbling/disable"
        try:
            self._client.post(path).raise_for_status()
        except httpx.HTTPError as exc:
            raise RobotBackendError(f"{path} failed: {exc}") from exc

    def _stop_active_move_locked(self) -> None:
        """Stops the move this backend last started, if any. Caller holds
        `_move_lock`. In 1.8.4, stopping a move that already finished
        returns 500 (unhandled KeyError), so an HTTP status error here
        usually just means the move had ended. The move is forgotten either
        way. A transport error means we can't know, and is logged."""
        uuid = self._active_move_uuid
        if uuid is None:
            return
        self._active_move_uuid = None
        try:
            self._client.post("/move/stop", json={"uuid": uuid}).raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.debug("stop of move %s not applied (likely already finished): %s", uuid, exc)
        except httpx.HTTPError as exc:
            log.warning("stop of move %s failed; it may still be running: %s", uuid, exc)

    def capture_frame(self, max_width: int | None = None) -> bytes:
        """Grabs one JPEG frame via the reachy_mini SDK's LOCAL media
        backend, per Pollen's documented media architecture
        (huggingface.co/docs/reachy_mini/SDK/media-architecture): the
        daemon always owns the camera and tees raw frames into a local
        GStreamer IPC endpoint (`unixfdsink`, /tmp/reachymini_camera_socket)
        capped at 10fps; `ReachyMini(media_backend="local").media.
        get_frame()` reads from that endpoint without touching the
        daemon's own camera/audio/WebRTC ownership.

        A prior version used the SDK's other documented path
        (`media_backend="no_media"` + direct /dev/video0 access via
        OpenCV, release_media()/acquire_media() around it) — the
        documented escape hatch for callers with no daemon on the same
        host, not the recommended same-host path. Verified live on the
        Nano (2026-09-24): it worked, but paid ~2.5-4s per call and
        briefly tore down the daemon's whole media pipeline (audio +
        WebRTC signalling) on every single-frame capture, motivating this
        switch to LOCAL, which shares the daemon's running pipeline
        instead of interrupting it.

        Keeps one `ReachyMini` instance alive for the process lifetime
        (never used as a context manager, so `__exit__`'s release/
        re-acquire never fires) rather than constructing one per call.
        UNVERIFIED against real hardware — the reachy-embodiment container
        does not yet bundle the `reachy_mini` SDK, PyGObject, or a
        GStreamer build with the `unixfdsrc` element it needs; see
        Dockerfile/pyproject.toml and docs/deployment.md for the
        corresponding image/mount changes this requires before this path
        can actually run on the Nano.

        `get_frame()` returns `None` if the camera isn't initialized yet
        (the daemon's docs confirm this for 1.8.4, the version pinned
        below to match the Nano's installed daemon) — most likely on the
        very first call right after this backend's process starts.
        Surfaced as `RobotBackendError`, the same clean-error contract
        every other real-hardware failure in this class uses, rather than
        letting a bare `None` reach `cv2.imencode` (which raises
        `cv2.error`, an unhandled 500 from the route's perspective).

        Explicitly passes `host`/`port` (parsed from this backend's own
        `base_url` in `__init__`) and `connection_mode="localhost_only"` —
        `ReachyMini`'s own default host is `reachy-mini.local` (mDNS),
        which this container has no particular reason to be able to
        resolve; `localhost_only` also skips any network/mDNS discovery
        attempt entirely, matching the same-host assumption this whole
        class already makes for its HTTP client.

        `self._mini_lock` guards construction: `GET /camera/frame` is a
        sync FastAPI route, run in Starlette's thread pool, so two
        requests arriving right after process start could otherwise race
        past the `self._mini is None` check and each construct their own
        `ReachyMini` against the same daemon socket.
        """
        import cv2  # local import: only needed by this one real-hardware path

        try:
            frame = self._media_client().media.get_frame()  # type: ignore[attr-defined]
        except Exception as exc:
            raise RobotBackendError(f"get_frame() failed: {exc}") from exc
        if frame is None:
            raise RobotBackendError("camera not initialized yet (get_frame() returned None)")
        if max_width is not None and frame.shape[1] > max_width:
            # Resizing first makes the Nano's JPEG encode cheaper too.
            height = round(frame.shape[0] * max_width / frame.shape[1])
            frame = cv2.resize(frame, (max_width, height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise RobotBackendError("failed to JPEG-encode captured frame")
        return bytes(encoded)

    def _media_client(self) -> object:
        """Lazily creates the one `ReachyMini` LOCAL media client shared by
        camera capture and the microphone (see capture_frame)."""
        if self._mini is None:
            with self._mini_lock:
                if self._mini is None:
                    try:
                        if self._media_client_factory is not None:
                            self._mini = self._media_client_factory()
                        else:
                            # local import: only real-hardware paths need the SDK
                            from reachy_mini import ReachyMini

                            self._mini = ReachyMini(
                                host=self._daemon_host,
                                port=self._daemon_port,
                                connection_mode="localhost_only",
                                media_backend="local",
                            )
                    except Exception as exc:
                        raise RobotBackendError(f"could not connect to daemon media backend: {exc}") from exc
        return self._mini

    def open_microphone(self) -> MicSource:
        return ReachyMiniMicSource(self._media_client().media)  # type: ignore[attr-defined]

    def stop_audio(self) -> None:
        """POST /media/stop_sound — stops the daemon's current play_sound.
        Source-checked against reachy_mini 1.8.4's daemon router
        (daemon/app/routers/media.py); not yet exercised live."""
        try:
            self._client.post("/media/stop_sound").raise_for_status()
        except httpx.HTTPError as exc:
            raise RobotBackendError(f"stop_sound failed: {exc}") from exc

    def play_audio(self, wav_bytes: bytes) -> float:
        """Uploads WAV bytes and plays them through the robot's speaker.

        Two daemon calls, per its API (no single upload-and-play
        endpoint): POST /media/sounds/upload (multipart) returns
        `{"status": "ok", "path": <absolute path>}`, then POST
        /media/play_sound {"file": ...} plays it. The response shape was
        confirmed from reachy_mini 1.8.4's daemon source (the pinned
        version matching the Nano), not from a live response; the other
        field names remain as a tolerant fallback. play_sound returns as
        soon as playback starts, so the WAV's own duration is returned for
        callers that need to wait for it to finish.
        """
        duration = wav_duration(wav_bytes)

        try:
            upload_resp = self._client.post(
                "/media/sounds/upload",
                files={"file": ("reachy_embodiment_audio.wav", wav_bytes, "audio/wav")},
            )
            upload_resp.raise_for_status()
            upload_body = upload_resp.json()
        except httpx.HTTPError as exc:
            raise RobotBackendError(f"audio upload to daemon failed: {exc}") from exc

        sound_path = None
        for key in ("path", "file", "filename", "name"):
            value = upload_body.get(key) if isinstance(upload_body, dict) else None
            if value:
                sound_path = value
                break
        if sound_path is None:
            raise RobotBackendError(f"could not find an uploaded file path in daemon response: {upload_body!r}")

        try:
            play_resp = self._client.post("/media/play_sound", json={"file": sound_path})
            play_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RobotBackendError(f"play_sound({sound_path!r}) failed: {exc}") from exc

        return duration

    def daemon_standby(self) -> dict[str, object]:
        """POST /daemon/stop?goto_sleep=true — the daemon's own dedicated
        rest routine (not the `sleep1` recorded emotion): interpolates the
        head to its canonical sleep pose, then de-torques every motor
        (`set_motor_control_mode(Disabled)`), stops the media server
        (releasing camera/audio) and closes the motor controller. Safe to
        physically handle the robot afterwards. Runs as a background job
        on the daemon (returns a `job_id` immediately, not full
        completion) and 409s if another start/stop/restart is already in
        progress — surfaced as RobotBackendError, not silently retried.
        UNVERIFIED against real hardware (found via /openapi.json + source
        during Phase 22b, not yet exercised live).

        Returns whatever `/daemon/status` reports immediately after the
        request is accepted — the park/de-torque sequence keeps running in
        the background, so this may still show a transitional state (e.g.
        "stopping") rather than the final "stopped"; callers that need the
        final state should poll `connected`/`sim` again after a moment,
        not treat this return value as completion."""
        # Our recorded move must not keep writing targets over the daemon's
        # own goto_sleep, so stop it first.
        with self._move_lock:
            self._stop_active_move_locked()
        try:
            resp = self._client.post("/daemon/stop", params={"goto_sleep": "true"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RobotBackendError(f"daemon standby (stop?goto_sleep=true) failed: {exc}") from exc
        return self._fetch_status() or {}

    def daemon_resume(self, *, wake_up: bool = True) -> dict[str, object]:
        """POST /daemon/start?wake_up=<bool> on the same daemon process
        put into standby by `daemon_standby()` — resumes the backend
        control loop and motor controller without a full systemd/process
        restart. `wake_up=True` replays the daemon's own wake-up motion,
        same as a normal daemon start. UNVERIFIED against real hardware
        (see `daemon_standby`'s note). Same transitional-status caveat as
        `daemon_standby` applies to the returned status."""
        try:
            resp = self._client.post("/daemon/start", params={"wake_up": "true" if wake_up else "false"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RobotBackendError(f"daemon resume (start?wake_up={wake_up}) failed: {exc}") from exc
        return self._fetch_status() or {}

    def close(self) -> None:
        """Releases the camera media client, if one was ever created.

        `ReachyMini` has no standalone public `close()`, only `__exit__`
        (used here directly rather than via `with`, since this instance
        was never entered as a context manager) — it closes the media
        manager and disconnects its own daemon client. Best-effort: called
        once from the app's shutdown lifespan, and a failure here shouldn't
        block the rest of shutdown, so it's logged rather than raised.
        """
        with self._move_lock:
            self._stop_active_move_locked()
        if self._mini is not None:
            try:
                self._mini.__exit__(None, None, None)  # type: ignore[attr-defined]
            except Exception:
                log.exception("error closing camera media client during shutdown")
            finally:
                self._mini = None
