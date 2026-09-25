"""Open-palm stop gesture (Phase 24e item 5, ADR 0023 addendum).

While the robot is speaking a reply, the camera is checked a few times a
second. Holding an open palm up to it stops playback, and the conversation
returns to listening. Frames are decoded and classified in memory only;
nothing is stored, logged or sent off the robot. Any hand counts: this is
a stop control, not identity.

MediaPipe is imported only when palm stop is enabled. Its aarch64 build is
not verified on the Nano's ARMv8.0 Cortex-A57, where another native ML
library (GStreamer's ONNX plugin) died with SIGILL. A signal kills the
whole process, so `probe_mediapipe` first loads the model and classifies a
blank frame in a child process. If the child dies, palm stop stays off and
the conversation carries on without it.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from collections.abc import Callable
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

OPEN_PALM = "Open_Palm"

# Where the embodiment image installs the pinned model (see its Dockerfile).
DEFAULT_PALM_MODEL_PATH = "/opt/models/gesture_recognizer.task"

# Consecutive positive frames required, and the minimum MediaPipe score.
# Two hits at the default interval is about half a second of a held palm,
# so a hand passing through the frame does not cut the reply.
DEFAULT_REQUIRED_HITS = 2
DEFAULT_MIN_SCORE = 0.6
DEFAULT_INTERVAL_SECONDS = 0.25


class PalmDetector(Protocol):
    def is_open_palm(self, jpeg: bytes) -> bool: ...

    def close(self) -> None: ...


class MediaPipePalmDetector:
    """MediaPipe's pretrained gesture recognizer in single-image mode."""

    def __init__(self, model_path: str, *, min_score: float = DEFAULT_MIN_SCORE) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self._min_score = min_score
        self._recognizer = vision.GestureRecognizer.create_from_options(
            vision.GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=2,
            )
        )

    def is_open_palm(self, jpeg: bytes) -> bool:
        import cv2
        import mediapipe as mp

        bgr = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return False
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        result = self._recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        return any(
            hand and hand[0].category_name == OPEN_PALM and hand[0].score >= self._min_score
            for hand in result.gestures
        )

    def close(self) -> None:
        self._recognizer.close()


_PROBE = """
import sys
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

recognizer = vision.GestureRecognizer.create_from_options(
    vision.GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_path=sys.argv[1]),
        running_mode=vision.RunningMode.IMAGE,
    )
)
recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((240, 320, 3), np.uint8)))
recognizer.close()
"""


def probe_mediapipe(model_path: str, *, timeout: float = 120.0) -> bool:
    """True if MediaPipe loads the model and classifies a frame in a child
    process. False on any failure, including death by signal."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE, model_path], capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("palm stop probe could not run: %s", exc)
        return False
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip().splitlines()[-1:] or [""]
        log.warning("palm stop probe failed (exit %s): %s", proc.returncode, tail[0])
        return False
    return True


class PalmStopWatcher:
    """Owns the detector for the process lifetime and watches for a held
    open palm during playback. `prepare` must succeed before `wait` is
    used; the voice loop skips palm stop when it returns False."""

    def __init__(
        self,
        capture_frame: Callable[[], bytes],
        detector_factory: Callable[[], PalmDetector],
        *,
        probe: Callable[[], bool] | None = None,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        required_hits: int = DEFAULT_REQUIRED_HITS,
    ) -> None:
        self._capture_frame = capture_frame
        self._detector_factory = detector_factory
        self._probe = probe
        self._interval = interval
        self._required_hits = required_hits
        self._detector: PalmDetector | None = None
        self._unavailable = False

    async def prepare(self) -> bool:
        """Loads the detector and warms the camera, off the event loop.
        The first camera frames can take 9–12 s on the Nano, so this runs
        at session start, not when the first reply begins. A failure
        disables palm stop for the rest of the process."""
        if self._detector is not None:
            return True
        if self._unavailable:
            return False
        try:
            if self._probe is not None and not await asyncio.to_thread(self._probe):
                raise RuntimeError("probe failed")
            self._detector = await asyncio.to_thread(self._detector_factory)
        except Exception as exc:  # noqa: BLE001 - palm stop is optional; the conversation continues
            log.warning("palm stop unavailable, continuing without it: %s", exc)
            self._unavailable = True
            return False
        try:
            await asyncio.to_thread(self._capture_frame)
        except Exception as exc:  # noqa: BLE001 - a late camera only delays detection
            log.info("palm stop camera warm-up failed, will retry during playback: %s", exc)
        log.info("palm stop ready")
        return True

    async def wait(self) -> None:
        """Returns once an open palm is seen in enough consecutive frames.
        Camera errors count as misses; the caller cancels this when
        playback ends."""
        detector = self._detector
        if detector is None:
            raise RuntimeError("palm stop used before prepare succeeded")
        hits = 0
        while True:
            try:
                frame = await asyncio.to_thread(self._capture_frame)
                seen = await asyncio.to_thread(detector.is_open_palm, frame)
            except Exception as exc:  # noqa: BLE001 - one bad frame is not a reason to stop watching
                log.debug("palm stop frame skipped: %s", exc)
                seen = False
            hits = hits + 1 if seen else 0
            if hits >= self._required_hits:
                return
            await asyncio.sleep(self._interval)

    def close(self) -> None:
        if self._detector is not None:
            self._detector.close()
            self._detector = None
