"""Open-palm stop watcher (Phase 24e item 5).

The watcher tests use a scripted camera and detector; no model runs. The
`slow` test at the end runs the real MediaPipe model on a real photo, and
is skipped unless both are supplied (neither is committed).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from reachy_embodiment.gesture import (
    MediaPipePalmDetector,
    PalmStopWatcher,
    probe_mediapipe,
)


class ScriptedDetector:
    def __init__(self, *answers: bool) -> None:
        self.answers = list(answers)
        self.seen: list[bytes] = []
        self.closed = 0

    def is_open_palm(self, jpeg: bytes) -> bool:
        self.seen.append(jpeg)
        return self.answers.pop(0) if self.answers else False

    def close(self) -> None:
        self.closed += 1


class Camera:
    def __init__(self, *, fail_on: set[int] = frozenset()) -> None:
        self.calls = 0
        self.fail_on = fail_on

    def __call__(self) -> bytes:
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("camera not initialized yet")
        return f"frame-{self.calls}".encode()


def watcher(camera, detector, **kwargs) -> PalmStopWatcher:
    return PalmStopWatcher(camera, lambda: detector, interval=0.0, **kwargs)


def test_needs_consecutive_open_palm_frames() -> None:
    async def scenario():
        camera = Camera()
        # A single hit is ignored; the miss resets the count.
        detector = ScriptedDetector(True, False, True, True)
        palm = watcher(camera, detector, required_hits=2)
        assert await palm.prepare()
        await asyncio.wait_for(palm.wait(), 1)
        return camera, detector

    camera, detector = asyncio.run(scenario())
    assert len(detector.seen) == 4
    assert camera.calls == 5  # one warm-up frame at prepare, then four watched


def test_camera_errors_count_as_misses() -> None:
    async def scenario():
        # Frame 1 is the warm-up; frame 3 fails between two hits.
        camera = Camera(fail_on={1, 3})
        detector = ScriptedDetector(True, True, True)
        palm = watcher(camera, detector, required_hits=2)
        assert await palm.prepare()  # a failed warm-up frame does not disable it
        await asyncio.wait_for(palm.wait(), 1)
        return detector

    detector = asyncio.run(scenario())
    assert detector.seen == [b"frame-2", b"frame-4", b"frame-5"]


def test_wait_keeps_watching_until_cancelled() -> None:
    async def scenario():
        palm = watcher(Camera(), ScriptedDetector())
        assert await palm.prepare()
        task = asyncio.create_task(palm.wait())
        await asyncio.sleep(0.05)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_failed_probe_or_load_disables_palm_stop_for_the_process() -> None:
    async def scenario(*, probe=None, load_fails: bool = False):
        loads = []

        def factory():
            loads.append(1)
            if load_fails:
                raise OSError("model missing")
            return ScriptedDetector()

        palm = PalmStopWatcher(Camera(), factory, probe=probe)
        first = await palm.prepare()
        second = await palm.prepare()
        return first, second, len(loads)

    assert asyncio.run(scenario(probe=lambda: False)) == (False, False, 0)
    assert asyncio.run(scenario(load_fails=True)) == (False, False, 1)
    assert asyncio.run(scenario(probe=lambda: True)) == (True, True, 1)  # loaded once


def test_wait_before_prepare_is_an_error() -> None:
    with pytest.raises(RuntimeError):
        asyncio.run(watcher(Camera(), ScriptedDetector()).wait())


def test_close_releases_the_detector() -> None:
    detector = ScriptedDetector()
    palm = watcher(Camera(), detector)
    asyncio.run(palm.prepare())
    palm.close()
    palm.close()
    assert detector.closed == 1


def test_probe_reports_failure_without_raising(tmp_path: Path) -> None:
    """A missing model makes the child process fail; the parent survives."""
    assert probe_mediapipe(str(tmp_path / "missing.task"), timeout=60) is False


def test_probe_survives_a_child_killed_by_a_signal(monkeypatch) -> None:
    """Stands in for SIGILL on an unsupported CPU: the child dies by signal."""
    from reachy_embodiment import gesture

    monkeypatch.setattr(gesture, "_PROBE", "import os, signal; os.kill(os.getpid(), signal.SIGILL)")
    assert probe_mediapipe("unused", timeout=30) is False


MODEL = os.environ.get("PALM_TEST_MODEL")
PALM_IMAGE = os.environ.get("PALM_TEST_IMAGE")
OTHER_IMAGE = os.environ.get("PALM_TEST_OTHER_IMAGE")


@pytest.mark.slow
@pytest.mark.skipif(
    not (MODEL and PALM_IMAGE and OTHER_IMAGE),
    reason="set PALM_TEST_MODEL, PALM_TEST_IMAGE (open palm) and PALM_TEST_OTHER_IMAGE (another gesture)",
)
@pytest.mark.skipif(sys.platform == "win32", reason="MediaPipe task model paths")
def test_real_model_tells_an_open_palm_from_another_gesture() -> None:
    assert probe_mediapipe(MODEL)
    detector = MediaPipePalmDetector(MODEL)
    try:
        assert detector.is_open_palm(Path(PALM_IMAGE).read_bytes())
        assert not detector.is_open_palm(Path(OTHER_IMAGE).read_bytes())
        assert not detector.is_open_palm(b"not a jpeg")
    finally:
        detector.close()
