"""Open-palm stop, hub side (Phase 24e item 5): counting and detector
failure with a scripted detector. The route is tested with the rest of the
robot voice path in test_robot_voice.py. The `slow` test runs the real
MediaPipe model on real photos, skipped unless both are supplied (neither
is committed).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from reachy_hub.palm_stop import MediaPipePalmDetector, PalmStop


class ScriptedDetector:
    def __init__(self, *answers: bool, fail_on: frozenset[int] = frozenset()) -> None:
        self.answers = list(answers)
        self.fail_on = fail_on
        self.calls = 0
        self.closed = 0

    def is_open_palm(self, jpeg: bytes) -> bool:
        self.calls += 1
        if self.calls in self.fail_on:
            raise ValueError("corrupt frame")
        return self.answers.pop(0) if self.answers else False

    def close(self) -> None:
        self.closed += 1


def run(palm: PalmStop, *frames: tuple[str, int]) -> list[bool]:
    async def scenario():
        return [await palm.check(sid, turn, b"jpeg") for sid, turn in frames]

    return asyncio.run(scenario())


def test_needs_consecutive_open_palms_in_the_same_reply() -> None:
    palm = PalmStop(lambda: ScriptedDetector(True, False, True, True, True, True))
    assert run(palm, *[("s", 1)] * 4) == [False, False, False, True]
    # The count starts again after a stop.
    assert run(palm, ("s", 1), ("s", 1)) == [False, True]


def test_a_new_reply_does_not_inherit_the_previous_count() -> None:
    palm = PalmStop(lambda: ScriptedDetector(True, True, True))
    assert run(palm, ("s", 1), ("s", 2), ("s", 2)) == [False, False, True]
    palm = PalmStop(lambda: ScriptedDetector(True, True))
    assert run(palm, ("a", 1), ("b", 1)) == [False, False]


def test_an_unclassifiable_frame_counts_as_no_palm() -> None:
    palm = PalmStop(lambda: ScriptedDetector(True, True, True, fail_on=frozenset({2})))
    assert run(palm, *[("s", 1)] * 4) == [False, False, False, True]


def test_a_detector_that_cannot_load_leaves_replies_playing() -> None:
    loads = []

    def factory():
        loads.append(1)
        raise RuntimeError("model missing")

    palm = PalmStop(factory)
    assert run(palm, *[("s", 1)] * 3) == [False, False, False]
    assert len(loads) == 1  # not retried on every frame


def test_close_releases_the_detector() -> None:
    detector = ScriptedDetector()
    palm = PalmStop(lambda: detector)
    run(palm, ("s", 1))
    palm.close()
    palm.close()
    assert detector.closed == 1


MODEL = os.environ.get("PALM_TEST_MODEL")
PALM_IMAGE = os.environ.get("PALM_TEST_IMAGE")
OTHER_IMAGE = os.environ.get("PALM_TEST_OTHER_IMAGE")


@pytest.mark.slow
@pytest.mark.skipif(
    not (MODEL and PALM_IMAGE and OTHER_IMAGE),
    reason="set PALM_TEST_MODEL, PALM_TEST_IMAGE (open palm) and PALM_TEST_OTHER_IMAGE (another gesture)",
)
def test_real_model_tells_an_open_palm_from_another_gesture() -> None:
    detector = MediaPipePalmDetector(MODEL)
    try:
        assert detector.is_open_palm(Path(PALM_IMAGE).read_bytes())
        assert not detector.is_open_palm(Path(OTHER_IMAGE).read_bytes())
        assert not detector.is_open_palm(b"not a jpeg")
    finally:
        detector.close()
