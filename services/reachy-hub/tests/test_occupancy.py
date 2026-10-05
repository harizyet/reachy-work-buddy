"""Occupancy sweep logic with a scripted robot and a scripted detector."""

import asyncio
import io
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from PIL import Image
from reachy_hub.occupancy import MediaPipeFaceDetector, check_occupancy

NOW = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)


class ScriptedRobot:
    def __init__(self, *, enabled=True, stops=5, fail_at=None, status_error=False):
        self.enabled, self.stops, self.fail_at, self.status_error = enabled, stops, fail_at, status_error
        self.visited: list[int] = []
        self.homed = 0

    async def sweep_status(self):
        if self.status_error:
            raise httpx.ConnectError("down")
        return {"enabled": self.enabled, "stops": self.stops}

    async def sweep_stop(self, index):
        if index == self.fail_at:
            raise httpx.ReadTimeout("slow")
        self.visited.append(index)
        return f"frame-{index}".encode()

    async def sweep_home(self):
        self.homed += 1

    async def get_camera_frame(self):
        return b"frame-forward"


class ScriptedDetector:
    def __init__(self, *people: bytes):
        self.people = set(people)

    def has_person(self, jpeg):
        return jpeg in self.people


def run(robot, detector):
    return asyncio.run(check_occupancy(robot, detector, now=lambda: NOW))


def test_sweep_visits_forward_first_and_stops_at_the_first_person_then_homes():
    robot = ScriptedRobot()
    result = run(robot, ScriptedDetector(b"frame-1"))
    assert robot.visited == [2, 1] and robot.homed == 1
    assert (result.present, result.method, result.stops_checked, result.checked_at) == (True, "sweep", 2, NOW)


def test_empty_room_visits_every_stop():
    robot = ScriptedRobot()
    result = run(robot, ScriptedDetector())
    assert sorted(robot.visited) == [0, 1, 2, 3, 4] and robot.homed == 1
    assert (result.present, result.method, result.stops_checked) == (False, "sweep", 5)


def test_failure_partway_reads_as_absent_and_still_homes_but_a_found_person_stands():
    robot = ScriptedRobot(fail_at=1)
    result = run(robot, ScriptedDetector())
    assert (result.present, result.method) == (False, "unavailable") and robot.homed == 1
    robot = ScriptedRobot(fail_at=0)
    assert run(robot, ScriptedDetector(b"frame-3")).present is True


def test_switch_off_uses_the_forward_frame_without_moving():
    robot = ScriptedRobot(enabled=False)
    result = run(robot, ScriptedDetector(b"frame-forward"))
    assert (result.present, result.method, result.stops_checked) == (True, "forward_frame", 1)
    assert robot.visited == [] and robot.homed == 0


def test_unreachable_robot_reads_as_absent():
    result = run(ScriptedRobot(status_error=True), ScriptedDetector())
    assert (result.present, result.method) == (False, "unavailable")


@pytest.mark.skipif(
    not os.environ.get("FACE_MODEL_PATH"), reason="set FACE_MODEL_PATH to blaze_face_short_range.tflite"
)
def test_mediapipe_detector_rejects_non_images_and_finds_no_face_in_a_blank_frame():
    detector = MediaPipeFaceDetector(os.environ["FACE_MODEL_PATH"])
    try:
        assert detector.has_person(b"not a jpeg") is False
        buf = io.BytesIO()
        Image.new("RGB", (320, 240), (20, 24, 32)).save(buf, format="JPEG")
        assert detector.has_person(buf.getvalue()) is False
        photo = os.environ.get("FACE_PHOTO")
        if photo:  # a real photo of a person facing the camera; never committed
            assert detector.has_person(Path(photo).read_bytes()) is True
    finally:
        detector.close()
