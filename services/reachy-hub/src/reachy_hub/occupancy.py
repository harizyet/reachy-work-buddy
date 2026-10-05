"""Room-occupancy check for alarm delivery (Phase 38.2, ADR 0027).

Asks reachy-embodiment to sweep through its fixed stops, one frame per stop,
and runs a person detector on each frame in memory. Frames are never stored
or logged, and the sweep stops at the first person. Only a boolean, a
timestamp and the stops covered leave this module. Anything that prevents a
conclusion (robot unreachable, sweep failing partway, detector error) reads
as nobody present, because the alarm then falls back to Telegram.

With the sweep switched off on the robot, the check uses the single forward
frame instead.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
import numpy as np

log = logging.getLogger(__name__)


class PersonDetector(Protocol):
    def has_person(self, jpeg: bytes) -> bool: ...


DEFAULT_FACE_MODEL_PATH = "/opt/models/blaze_face_short_range.tflite"
DEFAULT_MIN_SCORE = 0.5


class MediaPipeFaceDetector:
    """MediaPipe's short-range BlazeFace model in single-image mode. It finds
    a face turned toward the camera within a few metres; a person seen only
    from behind or far away is missed, which the Telegram fallback covers."""

    def __init__(self, model_path: str = DEFAULT_FACE_MODEL_PATH, *, min_score: float = DEFAULT_MIN_SCORE) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self._detector = vision.FaceDetector.create_from_options(
            vision.FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                min_detection_confidence=min_score,
            )
        )

    def has_person(self, jpeg: bytes) -> bool:
        import mediapipe as mp
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(io.BytesIO(jpeg)) as image:
                rgb = np.ascontiguousarray(np.asarray(image.convert("RGB")))
        except (UnidentifiedImageError, OSError):
            return False
        result = self._detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        return bool(result.detections)

    def close(self) -> None:
        self._detector.close()


@dataclass(frozen=True)
class OccupancyResult:
    present: bool
    checked_at: datetime
    method: str  # "sweep", "forward_frame" or "unavailable"
    stops_checked: int = 0


class EmbodimentFrames(Protocol):
    async def sweep_status(self) -> dict: ...
    async def sweep_stop(self, index: int) -> bytes: ...
    async def sweep_home(self) -> None: ...
    async def get_camera_frame(self) -> bytes: ...


async def check_occupancy(
    robot: EmbodimentFrames, detector: PersonDetector, *, now=lambda: datetime.now(UTC)
) -> OccupancyResult:
    try:
        status = await robot.sweep_status()
    except (httpx.HTTPError, ValueError):
        return OccupancyResult(False, now(), "unavailable")
    if not status.get("enabled"):
        try:
            frame = await robot.get_camera_frame()
            present = await asyncio.to_thread(detector.has_person, frame)
        except (httpx.HTTPError, RuntimeError, ValueError, OSError):
            return OccupancyResult(False, now(), "unavailable")
        return OccupancyResult(present, now(), "forward_frame", 1)

    checked = 0
    present = False
    complete = True
    moved = False
    try:
        # Forward stop first, then outwards: the likeliest place for a person
        # ends the sweep soonest.
        for index in _stop_order(int(status.get("stops", 0))):
            moved = True
            frame = await robot.sweep_stop(index)
            checked += 1
            if await asyncio.to_thread(detector.has_person, frame):
                present = True
                break
    except (httpx.HTTPError, RuntimeError, ValueError, OSError):
        complete = False
        log.warning("occupancy sweep failed after %d stop(s)", checked)
    finally:
        if moved:
            try:
                await robot.sweep_home()
            except httpx.HTTPError:
                log.warning("occupancy sweep could not return the head home")
    return OccupancyResult(present, now(), "sweep" if complete or present else "unavailable", checked)


def _stop_order(stops: int) -> list[int]:
    middle = stops // 2
    return sorted(range(stops), key=lambda i: (abs(i - middle), i))
