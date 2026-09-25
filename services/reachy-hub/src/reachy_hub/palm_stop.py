"""Open-palm stop, hub side (Phase 24e item 5, ADR 0023 addendum).

While a robot plays a reply, it uploads a few downscaled camera frames a
second to `ROBOT_PALM_FRAME`. Each frame is classified here in memory and
dropped: nothing is stored or logged. An open palm in enough consecutive
frames of the same reply tells the robot to stop that reply and listen
again. Any hand counts: this is a stop control, not identity.

Detection runs on the homelab rather than the robot so the robot image
carries no MediaPipe and the Nano's CPU is not loaded during playback.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Callable
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

OPEN_PALM = "Open_Palm"

# Where the hub image installs the pinned model (see its Dockerfile).
DEFAULT_PALM_MODEL_PATH = "/opt/models/gesture_recognizer.task"

# Consecutive positive frames required, and the minimum MediaPipe score.
# Two hits at the robot's upload interval is about half a second of a held
# palm, so a hand passing through the frame does not cut the reply.
DEFAULT_REQUIRED_HITS = 2
DEFAULT_MIN_SCORE = 0.6


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
        import mediapipe as mp
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(io.BytesIO(jpeg)) as image:
                rgb = np.ascontiguousarray(np.asarray(image.convert("RGB")))
        except (UnidentifiedImageError, OSError):
            return False
        result = self._recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        return any(
            hand and hand[0].category_name == OPEN_PALM and hand[0].score >= self._min_score
            for hand in result.gestures
        )

    def close(self) -> None:
        self._recognizer.close()


class PalmStop:
    """Owns the detector for the process lifetime and counts consecutive
    open-palm frames per reply. One robot's frames arrive one at a time,
    and the lock keeps the detector single-threaded across robots."""

    def __init__(
        self,
        detector_factory: Callable[[], PalmDetector],
        *,
        required_hits: int = DEFAULT_REQUIRED_HITS,
    ) -> None:
        self._detector_factory = detector_factory
        self._required_hits = required_hits
        self._detector: PalmDetector | None = None
        self._unavailable = False
        self._lock = asyncio.Lock()
        # (voice_session_id, turn) -> consecutive hits for that reply.
        self._hits: dict[tuple[str, int], int] = {}

    async def check(self, voice_session_id: str, turn: int, jpeg: bytes) -> bool:
        """True once this reply has seen enough consecutive open palms. A
        detector that cannot load, or a frame that cannot be classified,
        counts as no palm: the reply plays on."""
        async with self._lock:
            detector = await self._load()
            if detector is None:
                return False
            try:
                seen = await asyncio.to_thread(detector.is_open_palm, jpeg)
            except Exception as exc:  # noqa: BLE001 - one bad frame is not a reason to stop the reply
                log.debug("palm stop frame skipped: %s", exc)
                seen = False
            key = (voice_session_id, turn)
            # Only the reply now playing is tracked.
            self._hits = {key: self._hits.get(key, 0) + 1 if seen else 0}
            if self._hits[key] >= self._required_hits:
                self._hits.clear()
                return True
            return False

    async def _load(self) -> PalmDetector | None:
        if self._detector is None and not self._unavailable:
            try:
                self._detector = await asyncio.to_thread(self._detector_factory)
                log.info("palm stop ready")
            except Exception as exc:  # noqa: BLE001 - palm stop is optional; replies play to the end
                log.warning("palm stop unavailable, replies will play to the end: %s", exc)
                self._unavailable = True
        return self._detector

    def close(self) -> None:
        if self._detector is not None:
            self._detector.close()
            self._detector = None
