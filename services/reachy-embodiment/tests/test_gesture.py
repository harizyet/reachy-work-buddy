"""Open-palm stop, robot side (Phase 24e item 5): the frame uploader.

Scripted camera and hub; detection itself runs on the hub and is tested
there (services/reachy-hub/tests/test_palm_stop.py).
"""

from __future__ import annotations

import asyncio

import pytest
from reachy_embodiment.gesture import HubPalmStop, PalmStopGone


class Camera:
    def __init__(self, *, fail_on: frozenset[int] = frozenset()) -> None:
        self.calls = 0
        self.fail_on = fail_on

    def __call__(self) -> bytes:
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("camera not ready")
        return f"frame-{self.calls}".encode()


class Hub:
    """Answers stop on the given 1-based frame number."""

    def __init__(self, *, stop_on: int | None = None, gone_on: int | None = None, fail_on: frozenset[int] = frozenset()):
        self.frames: list[tuple[bytes, str, int, int]] = []
        self.stop_on = stop_on
        self.gone_on = gone_on
        self.fail_on = fail_on

    async def __call__(self, jpeg: bytes, voice_session_id: str, turn: int, generation: int) -> bool:
        self.frames.append((jpeg, voice_session_id, turn, generation))
        n = len(self.frames)
        if n == self.gone_on:
            raise PalmStopGone("reply ended")
        if n in self.fail_on:
            raise OSError("network blip")
        return n == self.stop_on


def test_returns_when_the_hub_says_stop_and_sends_the_reply_context() -> None:
    hub = Hub(stop_on=3)
    watcher = HubPalmStop(Camera(), hub, interval=0)
    asyncio.run(asyncio.wait_for(watcher.wait("session-1", 4, 7), 5))
    assert [f[0] for f in hub.frames] == [b"frame-1", b"frame-2", b"frame-3"]
    assert {f[1:] for f in hub.frames} == {("session-1", 4, 7)}


def test_camera_and_upload_errors_skip_a_frame() -> None:
    hub = Hub(stop_on=3, fail_on=frozenset({1}))
    camera = Camera(fail_on=frozenset({2}))
    asyncio.run(asyncio.wait_for(HubPalmStop(camera, hub, interval=0).wait("s", 1, 1), 5))
    assert camera.calls == 4  # frame 2 never reached the hub
    assert len(hub.frames) == 3


def test_hub_refusal_stops_uploading_until_playback_ends() -> None:
    async def scenario():
        hub = Hub(gone_on=2)
        watch = asyncio.ensure_future(HubPalmStop(Camera(), hub, interval=0).wait("s", 1, 1))
        await asyncio.sleep(0.05)
        assert not watch.done()
        assert len(hub.frames) == 2  # nothing after the refusal
        watch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await watch

    asyncio.run(scenario())


def test_prepare_warms_the_camera_and_tolerates_a_slow_one() -> None:
    camera = Camera(fail_on=frozenset({1}))
    assert asyncio.run(HubPalmStop(camera, Hub()).prepare()) is True
    assert camera.calls == 1
