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
    return ReachyDaemonBackend("http://daemon.test", transport=httpx.MockTransport(handler))


def test_connected_true_when_status_has_no_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Every reachy-mini-daemon route lives under /api — confirmed live
        # against the real daemon during Phase 22 Nano hardware testing.
        assert request.url.path == "/api/daemon/status"
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


def test_connected_false_when_daemon_stopped_even_without_error() -> None:
    # A daemon put into standby (POST /daemon/stop) keeps answering
    # /daemon/status with error=None — connected must not claim "yes"
    # just because there's no error field set.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": "stopped", "error": None})

    backend = make_backend(handler)
    assert backend.connected is False


def test_daemon_standby_posts_stop_with_goto_sleep_and_returns_status() -> None:
    calls: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.query.decode()))
        if request.url.path == "/api/daemon/stop":
            return httpx.Response(200, json={"job_id": "abc123"})
        return httpx.Response(200, json={"state": "stopping", "error": None})

    backend = make_backend(handler)
    status = backend.daemon_standby()

    assert ("POST", "/api/daemon/stop", "goto_sleep=true") in calls
    assert status == {"state": "stopping", "error": None}


def test_daemon_standby_raises_on_busy_conflict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Daemon is busy."})

    backend = make_backend(handler)
    with pytest.raises(RobotBackendError):
        backend.daemon_standby()


def test_daemon_resume_posts_start_with_wake_up_and_returns_status() -> None:
    calls: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.query.decode()))
        if request.url.path == "/api/daemon/start":
            return httpx.Response(200, json={"job_id": "def456"})
        return httpx.Response(200, json={"state": "running", "error": None})

    backend = make_backend(handler)
    status = backend.daemon_resume(wake_up=True)

    assert ("POST", "/api/daemon/start", "wake_up=true") in calls
    assert status == {"state": "running", "error": None}


def test_daemon_resume_can_skip_wake_up() -> None:
    calls: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.query.decode()))
        return httpx.Response(200, json={"state": "running", "error": None})

    backend = make_backend(handler)
    backend.daemon_resume(wake_up=False)

    assert ("POST", "/api/daemon/start", "wake_up=false") in calls


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
    assert calls == ["/api/move/play/recorded-move-dataset/pollen-robotics/reachy-mini-emotions-library/welcoming1"]


def test_play_behaviour_logs_and_does_not_raise_on_daemon_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no such move"})

    backend = make_backend(handler)
    backend.play_behaviour(Behaviour.GREETING, {})  # must not raise


def test_play_behaviour_skips_unmapped_behaviour_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called for an unmapped behaviour")

    backend = ReachyDaemonBackend("http://daemon.test", behaviour_moves={}, transport=httpx.MockTransport(handler))
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
    assert calls == ["/api/move/play/recorded-move-dataset/pollen-robotics/reachy-mini-emotions-library/waiting"]

    calls.clear()
    for behaviour in (Behaviour.IDLE_BREATHING, Behaviour.SUBTLE_SCAN, Behaviour.ANTENNA_TWITCH):
        backend.play_behaviour(behaviour, {})
    assert calls == []  # no daemon call at all: these are genuinely unmapped, not mapped-to-a-bad-move


def test_play_audio_uploads_then_plays_and_returns_duration() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/media/sounds/upload":
            return httpx.Response(200, json={"path": "sounds/tmp123.wav"})
        if request.url.path == "/api/media/play_sound":
            assert request.content
            return httpx.Response(200, json={"status": "ok"})
        raise AssertionError(f"unexpected path {request.url.path}")

    backend = make_backend(handler)
    duration = backend.play_audio(_wav_bytes(seconds=0.5))

    assert calls == ["/api/media/sounds/upload", "/api/media/play_sound"]
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


class _FakeMedia:
    def __init__(self, frame: np.ndarray | None) -> None:
        self._frame = frame if frame is not None else np.zeros((4, 4, 3), dtype=np.uint8)

    def get_frame(self) -> np.ndarray:
        return self._frame


class _FakeReachyMini:
    """Stand-in for `reachy_mini.ReachyMini(media_backend="local")`.

    Records how many times it was constructed so tests can confirm the
    backend keeps one instance alive across calls instead of rebuilding it
    (and re-touching the daemon's media pipeline) per capture.
    """

    instances = 0

    def __init__(self, frame: np.ndarray | None = None) -> None:
        _FakeReachyMini.instances += 1
        self.media = _FakeMedia(frame)


def test_capture_frame_reads_via_local_media_backend() -> None:
    mini = _FakeReachyMini()
    backend = ReachyDaemonBackend("http://daemon.test", media_client_factory=lambda: mini)

    frame = backend.capture_frame()

    assert isinstance(frame, bytes)
    assert len(frame) > 0  # a real JPEG encode of the fake frame


def test_capture_frame_reuses_one_media_client_across_calls() -> None:
    _FakeReachyMini.instances = 0
    backend = ReachyDaemonBackend("http://daemon.test", media_client_factory=_FakeReachyMini)

    backend.capture_frame()
    backend.capture_frame()

    # Constructing ReachyMini per call would re-run its daemon handshake on
    # every single capture; this is the exact overhead the LOCAL-backend
    # switch was meant to avoid (the prior release/acquire approach paid
    # it every time — see robot.py's capture_frame docstring).
    assert _FakeReachyMini.instances == 1


def test_capture_frame_raises_if_jpeg_encode_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = ReachyDaemonBackend("http://daemon.test", media_client_factory=_FakeReachyMini)
    monkeypatch.setattr(cv2, "imencode", lambda *_args: (False, None))

    with pytest.raises(RobotBackendError):
        backend.capture_frame()
