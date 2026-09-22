"""Unit tests for ReachyDaemonBackend against a fake daemon HTTP transport.

No real reachy-mini-daemon, network, or hardware is involved — httpx.MockTransport
intercepts every request. This proves the request/response wiring is correct
given the *assumed* daemon API shapes documented in robot.py and
docs/verification/phase-22-inventory-2026-09-22.md; it cannot prove those
assumed shapes match the real daemon. See robot.py's module docstring:
ReachyDaemonBackend is a first draft pending live verification.
"""

from __future__ import annotations

import wave
from io import BytesIO

import cv2
import httpx
import numpy as np
import pytest
from reachy_embodiment.robot import ReachyDaemonBackend, RobotBackendError

from shared.models.embodiment import Behaviour


def _wav_bytes(seconds: float = 0.5, framerate: int = 16000) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * int(seconds * framerate))
    return buf.getvalue()


def make_backend(handler) -> ReachyDaemonBackend:
    backend = ReachyDaemonBackend("http://daemon.test")
    backend._client = httpx.Client(base_url="http://daemon.test", transport=httpx.MockTransport(handler))
    return backend


def test_connected_true_when_status_has_no_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/daemon/status"
        return httpx.Response(200, json={"state": "ready", "error": None})

    backend = make_backend(handler)
    assert backend.connected is True


def test_connected_false_when_status_reports_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": "error", "error": "daemon lost motor controller"})

    backend = make_backend(handler)
    assert backend.connected is False


def test_connected_false_when_daemon_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    backend = make_backend(handler)
    assert backend.connected is False


def test_sim_reflects_daemon_simulation_flags() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"simulation_enabled": True, "mockup_sim_enabled": False, "error": None})

    backend = make_backend(handler)
    assert backend.sim is True


def test_sim_false_when_daemon_reports_real_hardware() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"simulation_enabled": False, "mockup_sim_enabled": False, "error": None})

    backend = make_backend(handler)
    assert backend.sim is False


def test_sim_defaults_true_when_daemon_unreachable() -> None:
    """Unknown daemon state must not be reported as confirmed real hardware."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    backend = make_backend(handler)
    assert backend.sim is True


def test_play_behaviour_posts_to_mapped_move() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"uuid": "abc"})

    backend = make_backend(handler)
    backend.play_behaviour(Behaviour.GREETING, {})
    assert calls == ["/move/play/recorded-move-dataset/pollen-robotics/reachy-mini-emotions-library/welcoming1"]


def test_play_behaviour_logs_and_does_not_raise_on_daemon_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no such move"})

    backend = make_backend(handler)
    backend.play_behaviour(Behaviour.GREETING, {})  # must not raise


def test_play_behaviour_skips_unmapped_behaviour_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called for an unmapped behaviour")

    backend = ReachyDaemonBackend("http://daemon.test", behaviour_moves={})
    backend._client = httpx.Client(base_url="http://daemon.test", transport=httpx.MockTransport(handler))
    backend.play_behaviour(Behaviour.GREETING, {})  # must not raise


def test_default_mapping_uses_real_verified_move_names() -> None:
    """Locks in the real, live-verified move library (Phase 22 Nano
    testing) as the default mapping, and locks in that the continuous
    idle-loop behaviours are deliberately left unmapped rather than
    forced onto a misleading one-shot emotive move — see robot.py's
    _DEFAULT_BEHAVIOUR_MOVES comment for why."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"uuid": "abc"})

    backend = make_backend(handler)

    backend.play_behaviour(Behaviour.WAITING, {})
    assert calls == ["/move/play/recorded-move-dataset/pollen-robotics/reachy-mini-emotions-library/waiting"]

    calls.clear()
    for behaviour in (Behaviour.IDLE_BREATHING, Behaviour.SUBTLE_SCAN, Behaviour.ANTENNA_TWITCH):
        backend.play_behaviour(behaviour, {})
    assert calls == []  # no daemon call at all: these are genuinely unmapped, not mapped-to-a-bad-move


def test_play_audio_uploads_then_plays_and_returns_duration() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/media/sounds/upload":
            return httpx.Response(200, json={"path": "sounds/tmp123.wav"})
        if request.url.path == "/media/play_sound":
            assert request.content
            return httpx.Response(200, json={"status": "ok"})
        raise AssertionError(f"unexpected path {request.url.path}")

    backend = make_backend(handler)
    duration = backend.play_audio(_wav_bytes(seconds=0.5))

    assert calls == ["/media/sounds/upload", "/media/play_sound"]
    assert duration == pytest.approx(0.5)


def test_play_audio_raises_if_upload_response_has_no_recognizable_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected_key": "value"})

    backend = make_backend(handler)
    with pytest.raises(RobotBackendError):
        backend.play_audio(_wav_bytes())


def test_play_audio_raises_on_upload_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "disk full"})

    backend = make_backend(handler)
    with pytest.raises(RobotBackendError):
        backend.play_audio(_wav_bytes())


class _FakeCapture:
    def __init__(self, *, opens: bool = True, reads: bool = True) -> None:
        self.opens = opens
        self.reads = reads
        self.released = False

    def isOpened(self) -> bool:
        return self.opens

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.reads:
            return False, None
        return True, np.zeros((4, 4, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released = True


def test_capture_frame_releases_and_reacquires_daemon_media(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"status": "ok"})

    backend = make_backend(handler)

    fake_capture = _FakeCapture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda _device: fake_capture)

    frame = backend.capture_frame()

    assert calls == ["/media/release", "/media/acquire"]
    assert fake_capture.released is True
    assert isinstance(frame, bytes)
    assert len(frame) > 0  # a real JPEG encode of the fake frame


def test_capture_frame_reacquires_media_even_if_read_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"status": "ok"})

    backend = make_backend(handler)
    fake_capture = _FakeCapture(reads=False)
    monkeypatch.setattr(cv2, "VideoCapture", lambda _device: fake_capture)

    with pytest.raises(RobotBackendError):
        backend.capture_frame()

    # /media/acquire must still have been called despite the failure, so
    # the daemon isn't left permanently locked out of its own camera.
    assert calls == ["/media/release", "/media/acquire"]
    assert fake_capture.released is True


def test_capture_frame_raises_if_daemon_will_not_release_media() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "already released"})

    backend = make_backend(handler)
    with pytest.raises(RobotBackendError):
        backend.capture_frame()
