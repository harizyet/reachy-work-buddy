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
above this module changes.

**`ReachyDaemonBackend` is a first draft, not yet verified against a live
daemon** — reachy-mini-daemon has not been started during Phase 22
verification so far (starting it moves the robot via `--wake-up-on-start`
by default and needs the owner physically present/supervising). Its move
dataset/name mapping, upload-response field name, and status field
semantics are all best-effort reads of the daemon's source, not confirmed
live responses. Treat every "unverified" note below as a real gap to close
before trusting this in production, not hedging.
"""

from __future__ import annotations

import io
import logging
import time
import wave
from typing import Protocol

import httpx
from PIL import Image, ImageDraw

from shared.models.embodiment import Behaviour

log = logging.getLogger(__name__)

_FRAME_SIZE = (320, 240)


class RobotBackend(Protocol):
    @property
    def connected(self) -> bool: ...

    @property
    def sim(self) -> bool: ...

    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None: ...

    def capture_frame(self) -> bytes:
        """Returns a single JPEG-encoded camera frame. Phase 16/ADR 0013."""
        ...

    def play_audio(self, wav_bytes: bytes) -> float:
        """Plays 16-bit PCM WAV bytes through the robot's speaker, returns
        the audio's duration in seconds. Phase 16/ADR 0013."""
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

    def capture_frame(self) -> bytes:
        # No physical camera exists in this environment. The marker's
        # position is derived from wall-clock time so consecutive polls
        # visibly differ — proof a live transport is delivering fresh
        # frames, not a cached static image, the same purpose
        # play_behaviour's log line serves for motion.
        width, height = _FRAME_SIZE
        image = Image.new("RGB", (width, height), color=(20, 24, 32))
        draw = ImageDraw.Draw(image)
        x = int((time.monotonic() % 2.0) / 2.0 * (width - 12))
        draw.rectangle([x, 0, x + 12, height], fill=(91, 140, 255))
        draw.text((8, 8), "SIMULATED CAMERA", fill=(238, 238, 238))
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=70)
        return buf.getvalue()

    def play_audio(self, wav_bytes: bytes) -> float:
        with io.BytesIO(wav_bytes) as buf, wave.open(buf, "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        log.info("sim: playing %.2fs of audio (no physical speaker in this environment)", duration)
        return duration


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
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=command_timeout)
        self._status_timeout = status_timeout
        self._behaviour_moves = behaviour_moves if behaviour_moves is not None else dict(_DEFAULT_BEHAVIOUR_MOVES)

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
        return status is not None and not status.get("error")

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

    def capture_frame(self) -> bytes:
        """Grabs one JPEG frame directly from /dev/video0 via V4L2/OpenCV.

        The daemon exposes no REST single-frame endpoint (camera access is
        WebRTC-only) — see docs/verification/phase-22-inventory-
        2026-09-22.md's daemon API section. This releases the daemon's own
        media ownership first (POST /media/release), opens the device
        directly, grabs one frame, and always re-acquires (POST
        /media/acquire) afterwards, even on failure, so a failed capture
        doesn't leave the daemon permanently locked out of its own camera.
        UNVERIFIED against real hardware.
        """
        import cv2  # local import: only needed by this one real-hardware path

        try:
            resp = self._client.post("/media/release")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RobotBackendError(f"could not release camera from daemon: {exc}") from exc

        try:
            capture = cv2.VideoCapture("/dev/video0")
            try:
                if not capture.isOpened():
                    raise RobotBackendError("/dev/video0 did not open")
                ok, frame = capture.read()
                if not ok:
                    raise RobotBackendError("failed to read a frame from /dev/video0")
                ok, encoded = cv2.imencode(".jpg", frame)
                if not ok:
                    raise RobotBackendError("failed to JPEG-encode captured frame")
                return bytes(encoded)
            finally:
                capture.release()
        finally:
            try:
                resp = self._client.post("/media/acquire")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                # Logged, not raised: raising here would mask whatever
                # capture-path exception is already propagating (or, on
                # the success path, would turn a successful capture into a
                # failure over an unrelated handoff problem). The daemon
                # being left without media ownership is a real problem,
                # just not one this call can fix by raising louder.
                log.error("could not re-acquire camera for daemon after capture: %s", exc)

    def play_audio(self, wav_bytes: bytes) -> float:
        """Uploads WAV bytes and plays them through the robot's speaker.

        Two daemon calls, per its API (no single upload-and-play
        endpoint): POST /media/sounds/upload (multipart) returns a server
        path, then POST /media/play_sound {"file": ...} plays it. The
        upload response's exact field name is UNVERIFIED (no live
        response has been inspected); this tries the field names that
        look plausible from the daemon's own upload-handling code and
        raises clearly if none match, rather than guessing further.
        """
        with io.BytesIO(wav_bytes) as buf, wave.open(buf, "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()

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
