"""Unit tests for ReachyDaemonBackend against a fake daemon HTTP transport.

No real reachy-mini-daemon, network, or hardware is involved — httpx.MockTransport
intercepts every request. This proves the request/response wiring is correct
given the *assumed* daemon API shapes documented in robot.py and
docs/verification/phase-22-inventory-2026-09-22.md; it cannot prove those
assumed shapes match the real daemon. See robot.py's module docstring:
ReachyDaemonBackend is a first draft pending live verification.
"""

from __future__ import annotations

import json
import sys
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


_MOVE_PREFIX = "/api/move/play/recorded-move-dataset/pollen-robotics/reachy-mini-emotions-library/"


def _move_daemon(calls: list[tuple[str, object]], *, stop_status: int = 200):
    """Fake daemon handing out sequential move UUIDs and recording stops."""
    counter = iter(range(1, 100))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/move/stop":
            calls.append(("stop", json.loads(request.content)["uuid"]))
            return httpx.Response(stop_status, json={})
        if request.url.path.startswith(_MOVE_PREFIX):
            calls.append(("play", request.url.path.removeprefix(_MOVE_PREFIX)))
            return httpx.Response(200, json={"uuid": f"move-{next(counter)}"})
        calls.append(("other", request.url.path))
        return httpx.Response(200, json={"state": "running"})

    return handler


def test_play_behaviour_stops_previous_move_before_starting_next() -> None:
    """reachy-mini 1.8.4 runs overlapping REST moves concurrently, so the
    backend must stop its own previous move before starting another."""
    calls: list[tuple[str, object]] = []
    backend = make_backend(_move_daemon(calls))

    backend.play_behaviour(Behaviour.LISTENING, {})
    backend.play_behaviour(Behaviour.THINKING, {})

    assert calls == [("play", "attentive1"), ("stop", "move-1"), ("play", "thoughtful1")]


def test_play_behaviour_proceeds_when_previous_move_already_finished() -> None:
    """1.8.4 answers 500 when stopping a move that already ended."""
    calls: list[tuple[str, object]] = []
    backend = make_backend(_move_daemon(calls, stop_status=500))

    backend.play_behaviour(Behaviour.LISTENING, {})
    backend.play_behaviour(Behaviour.THINKING, {})
    backend.play_behaviour(Behaviour.WAITING, {})

    assert calls == [
        ("play", "attentive1"),
        ("stop", "move-1"),
        ("play", "thoughtful1"),
        ("stop", "move-2"),
        ("play", "waiting"),
    ]


def test_failed_play_leaves_nothing_to_stop() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(404, json={"detail": "no such move"})

    backend = make_backend(handler)
    backend.play_behaviour(Behaviour.LISTENING, {})
    backend.play_behaviour(Behaviour.THINKING, {})

    assert "/api/move/stop" not in calls


def test_unmapped_behaviour_does_not_stop_active_move() -> None:
    calls: list[tuple[str, object]] = []
    backend = make_backend(_move_daemon(calls))

    backend.play_behaviour(Behaviour.LISTENING, {})
    backend.play_behaviour(Behaviour.IDLE_BREATHING, {})

    assert calls == [("play", "attentive1")]


def test_standby_stops_active_move_before_goto_sleep() -> None:
    calls: list[tuple[str, object]] = []
    backend = make_backend(_move_daemon(calls))

    backend.play_behaviour(Behaviour.LISTENING, {})
    backend.daemon_standby()

    assert calls[:3] == [("play", "attentive1"), ("stop", "move-1"), ("other", "/api/daemon/stop")]


def test_close_stops_active_move_once() -> None:
    calls: list[tuple[str, object]] = []
    backend = make_backend(_move_daemon(calls))

    backend.play_behaviour(Behaviour.LISTENING, {})
    backend.close()
    backend.close()

    assert calls == [("play", "attentive1"), ("stop", "move-1")]


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
    def __init__(self, frame: np.ndarray | None, *, frame_is_none: bool = False) -> None:
        if frame_is_none:
            self._frame: np.ndarray | None = None
        else:
            self._frame = frame if frame is not None else np.zeros((4, 4, 3), dtype=np.uint8)

    def get_frame(self) -> np.ndarray | None:
        return self._frame


class _FakeReachyMini:
    """Stand-in for `reachy_mini.ReachyMini(media_backend="local")`.

    Records how many times it was constructed so tests can confirm the
    backend keeps one instance alive across calls instead of rebuilding it
    (and re-touching the daemon's media pipeline) per capture.
    """

    instances = 0

    def __init__(self, frame: np.ndarray | None = None, *, frame_is_none: bool = False) -> None:
        _FakeReachyMini.instances += 1
        self.media = _FakeMedia(frame, frame_is_none=frame_is_none)


def test_capture_frame_reads_via_local_media_backend() -> None:
    mini = _FakeReachyMini()
    backend = ReachyDaemonBackend("http://daemon.test", media_client_factory=lambda: mini)

    frame = backend.capture_frame()

    assert isinstance(frame, bytes)
    assert len(frame) > 0  # a real JPEG encode of the fake frame


def test_capture_frame_downscales_for_palm_stop_frames() -> None:
    mini = _FakeReachyMini(np.zeros((1080, 1920, 3), dtype=np.uint8))
    backend = ReachyDaemonBackend("http://daemon.test", media_client_factory=lambda: mini)

    small = cv2.imdecode(np.frombuffer(backend.capture_frame(max_width=640), np.uint8), cv2.IMREAD_COLOR)
    full = cv2.imdecode(np.frombuffer(backend.capture_frame(), np.uint8), cv2.IMREAD_COLOR)

    assert small.shape[:2] == (360, 640)
    assert full.shape[:2] == (1080, 1920)


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


def test_capture_frame_raises_cleanly_if_get_frame_returns_none() -> None:
    # 1.8.4's get_frame() returns None if the camera isn't initialized yet
    # — most likely on the very first call right after process start. This
    # must surface as RobotBackendError, not an unhandled cv2.error from
    # passing None straight to cv2.imencode.
    backend = ReachyDaemonBackend(
        "http://daemon.test", media_client_factory=lambda: _FakeReachyMini(frame=None, frame_is_none=True)
    )

    with pytest.raises(RobotBackendError):
        backend.capture_frame()


def test_capture_frame_uses_explicit_localhost_only_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, object] = {}

    class _FakeReachyMiniModule:
        @staticmethod
        def ReachyMini(**kwargs: object) -> _FakeReachyMini:
            captured_kwargs.update(kwargs)
            return _FakeReachyMini()

    monkeypatch.setitem(sys.modules, "reachy_mini", _FakeReachyMiniModule())

    # No media_client_factory here — exercises the real (module-level)
    # `from reachy_mini import ReachyMini` branch against the fake module.
    backend = ReachyDaemonBackend("http://192.0.2.10:9000")
    backend.capture_frame()

    # Must never rely on ReachyMini's own default host (mDNS
    # "reachy-mini.local") or auto-detected connection mode — derived
    # explicitly from this backend's own base_url instead.
    assert captured_kwargs["host"] == "192.0.2.10"
    assert captured_kwargs["port"] == 9000
    assert captured_kwargs["connection_mode"] == "localhost_only"
    assert captured_kwargs["media_backend"] == "local"


def test_capture_frame_wraps_construction_failure() -> None:
    def factory() -> _FakeReachyMini:
        raise RuntimeError("daemon socket not found")

    backend = ReachyDaemonBackend("http://daemon.test", media_client_factory=factory)

    with pytest.raises(RobotBackendError):
        backend.capture_frame()


def test_capture_frame_wraps_get_frame_failure() -> None:
    class _BrokenMedia:
        def get_frame(self) -> np.ndarray:
            raise RuntimeError("socket closed")

    class _BrokenReachyMini:
        def __init__(self) -> None:
            self.media = _BrokenMedia()

    backend = ReachyDaemonBackend("http://daemon.test", media_client_factory=_BrokenReachyMini)

    with pytest.raises(RobotBackendError):
        backend.capture_frame()


def test_close_exits_media_client_and_clears_it() -> None:
    exit_calls = []

    class _ExitTrackingReachyMini(_FakeReachyMini):
        def __exit__(self, *args: object) -> None:
            exit_calls.append(args)

    backend = ReachyDaemonBackend("http://daemon.test", media_client_factory=_ExitTrackingReachyMini)
    backend.capture_frame()  # creates self._mini

    backend.close()

    assert exit_calls == [(None, None, None)]
    # Idempotent: closing again (no media client left) must not raise.
    backend.close()


def test_close_without_ever_capturing_is_a_noop() -> None:
    backend = ReachyDaemonBackend("http://daemon.test")
    backend.close()  # no error even though self._mini was never created


def _goto_daemon(calls: list[tuple[str, object]]):
    """_move_daemon plus /move/goto and the wobbling routes."""
    moves = _move_daemon(calls)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/move/goto":
            calls.append(("goto", json.loads(request.content)))
            return httpx.Response(200, json={"uuid": "goto-1"})
        if request.url.path.startswith("/api/media/wobbling/"):
            calls.append(("wobble", request.url.path.rsplit("/", 1)[1]))
            return httpx.Response(200, json={"status": "ok"})
        return moves(request)

    return handler


def test_goto_home_stops_previous_move_and_is_itself_stoppable() -> None:
    calls: list[tuple[str, object]] = []
    backend = make_backend(_goto_daemon(calls))

    backend.play_behaviour(Behaviour.THINKING, {})
    backend.goto_home()
    backend.stop_motion()
    backend.stop_motion()

    assert [c[0] for c in calls] == ["play", "stop", "goto", "stop"]
    assert calls[1] == ("stop", "move-1")
    assert calls[3] == ("stop", "goto-1")


def test_goto_home_payload_is_the_184_wake_up_pose_with_explicit_body_yaw() -> None:
    """Validated against the daemon's own request model: in 1.8.4 a
    misspelled pose key silently validates as identity, so check every
    field resolves, not just that the request is accepted."""
    move = pytest.importorskip("reachy_mini.daemon.app.routers.move")
    models = pytest.importorskip("reachy_mini.daemon.app.models")
    from reachy_embodiment.robot import HOME_GOTO
    from reachy_mini.reachy_mini import INIT_ANTENNAS_JOINT_POSITIONS

    request = move.GotoModelRequest.model_validate(HOME_GOTO)
    assert isinstance(request.head_pose, models.XYZRPYPose)
    assert request.head_pose.model_dump() == HOME_GOTO["head_pose"]
    assert list(request.antennas) == INIT_ANTENNAS_JOINT_POSITIONS
    assert request.body_yaw == 0.0
    assert 0 < request.duration <= 2.0
    assert "interpolation" not in HOME_GOTO  # REST ignores it in 1.8.4


def test_goto_home_failure_is_logged_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "Backend not running"})

    backend = make_backend(handler)
    backend.goto_home()
    backend.stop_motion()  # nothing remembered to stop


def test_speech_wobble_routes_and_failure() -> None:
    calls: list[tuple[str, object]] = []
    backend = make_backend(_goto_daemon(calls))
    backend.set_speech_wobble(True)
    backend.set_speech_wobble(False)
    assert calls == [("wobble", "enable"), ("wobble", "disable")]

    failing = make_backend(lambda request: httpx.Response(503, json={}))
    with pytest.raises(RobotBackendError):
        failing.set_speech_wobble(True)
