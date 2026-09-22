"""Robot backend abstraction.

Phase 2 only needs the semantic HTTP layer to prove it can drive *something*
named after a behaviour; it does not need real Reachy hardware. This mirrors
Jarvis's own RobotController, which exposes a `sim` property precisely so the
rest of the stack doesn't care whether hardware is attached (see
docs/jarvis-baseline.md, robot/controller.py section).

A real Reachy-backed implementation (wrapping the `reachy_mini` SDK the way
Jarvis's RobotController does) is added when hardware is available to test
against; it plugs in behind the same RobotBackend protocol so nothing above
this module changes.
"""

from __future__ import annotations

import io
import logging
import time
import wave
from typing import Protocol

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
