from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app
from reachy_embodiment.motion import MotionController
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_embodiment.state import ServiceState

from shared.models.embodiment import Behaviour, EmbodimentState


def make_client() -> TestClient:
    # run_presence_loop=False: these tests assert exact state after specific
    # actions, which would race against the background idle-animation thread
    # (see test_presence.py and test_app_presence_loop.py for that behaviour).
    return TestClient(create_app(SimulatedRobotBackend(), run_presence_loop=False))


def test_health() -> None:
    client = make_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_state_defaults_to_idle() -> None:
    client = make_client()
    resp = client.get("/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["embodiment_state"] == EmbodimentState.IDLE.value
    assert body["last_behaviour"] is None
    assert body["sim"] is True


def test_behaviours_catalogue_lists_every_behaviour() -> None:
    client = make_client()
    resp = client.get("/behaviours")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {b.value for b in Behaviour}
    assert all(isinstance(v, str) and v for v in body.values())


def test_post_behaviour_triggers_it_and_updates_state() -> None:
    client = make_client()
    resp = client.post("/behaviour/listening")
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_behaviour"] == Behaviour.LISTENING.value
    assert body["embodiment_state"] == EmbodimentState.LISTENING.value
    assert body["last_behaviour_at"] is not None

    # State persists across the next GET /state call.
    resp = client.get("/state")
    assert resp.json()["last_behaviour"] == Behaviour.LISTENING.value


def test_daemon_standby_sets_sleep_state_and_returns_daemon_status() -> None:
    client = make_client()
    resp = client.post("/daemon/standby")
    assert resp.status_code == 200
    body = resp.json()
    assert body["embodiment_state"] == EmbodimentState.SLEEP.value
    assert body["connected"] is False
    assert body["daemon_status"] == {"state": "stopped", "simulation_enabled": True}


def test_daemon_resume_returns_to_idle_and_reconnects() -> None:
    client = make_client()
    client.post("/daemon/standby")
    resp = client.post("/daemon/resume")
    assert resp.status_code == 200
    body = resp.json()
    assert body["embodiment_state"] == EmbodimentState.IDLE.value
    assert body["connected"] is True
    assert body["daemon_status"] == {"state": "running", "simulation_enabled": True}


def test_post_gesture_behaviour_does_not_change_standing_state() -> None:
    client = make_client()
    client.post("/behaviour/listening")
    resp = client.post("/behaviour/acknowledgement")
    body = resp.json()
    assert body["last_behaviour"] == Behaviour.ACKNOWLEDGEMENT.value
    # ACKNOWLEDGEMENT has no STATE_FOR_BEHAVIOUR entry, so the standing
    # state (set by the previous LISTENING call) should be unchanged.
    assert body["embodiment_state"] == EmbodimentState.LISTENING.value


def test_post_unknown_behaviour_is_404() -> None:
    client = make_client()
    resp = client.post("/behaviour/moonwalk")
    assert resp.status_code == 404


def test_post_behaviour_with_correlation_id_and_parameters() -> None:
    client = make_client()
    resp = client.post(
        "/behaviour/greeting",
        json={"parameters": {"user": "hariz"}, "correlation_id": "abc-123"},
    )
    assert resp.status_code == 200
    assert resp.json()["last_behaviour"] == Behaviour.GREETING.value


def test_post_unknown_behaviour_with_body_is_still_404_not_422() -> None:
    """The path segment is the source of truth; an invalid path behaviour
    must 404 regardless of what's in the body (see BehaviourBody docstring
    in app.py for the bug this guards against)."""
    client = make_client()
    resp = client.post("/behaviour/moonwalk", json={"parameters": {"foo": "bar"}})
    assert resp.status_code == 404


def test_heartbeat_endpoint_updates_last_heartbeat_at() -> None:
    client = make_client()
    assert client.get("/state").json()["last_heartbeat_at"] is None

    resp = client.post("/heartbeat")
    assert resp.status_code == 200
    assert resp.json()["last_heartbeat_at"] is not None


def test_behaviour_command_counts_as_heartbeat() -> None:
    client = make_client()
    resp = client.post("/behaviour/listening")
    assert resp.json()["last_heartbeat_at"] is not None


class RecordingSimBackend(SimulatedRobotBackend):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def play_behaviour(self, name, parameters) -> None:
        self.calls.append(f"play:{name.value}")

    def stop_motion(self) -> None:
        self.calls.append("stop")

    def daemon_standby(self) -> dict[str, object]:
        self.calls.append("standby")
        return super().daemon_standby()


def test_behaviour_rejected_with_409_while_robot_conversation_owns_motion() -> None:
    backend = RecordingSimBackend()
    motion = MotionController(backend, ServiceState(), conversation_motion=True, threaded=False)
    client = TestClient(create_app(backend, run_presence_loop=False, motion=motion))
    token = motion.begin_conversation()

    resp = client.post("/behaviour/greeting")
    assert resp.status_code == 409
    assert "play:greeting" not in backend.calls
    assert client.get("/state").json()["last_behaviour"] is None

    motion.end_conversation(token, completed=False)
    motion.run_pending()
    assert client.post("/behaviour/greeting").status_code == 200
    assert backend.calls[-1] == "play:greeting"


def test_behaviour_allowed_during_conversation_when_motion_switches_are_off() -> None:
    backend = RecordingSimBackend()
    client = TestClient(create_app(backend, run_presence_loop=False))
    client.app.state.motion.begin_conversation()
    assert client.post("/behaviour/greeting").status_code == 200


def test_standby_stops_motion_before_the_daemon_parks() -> None:
    backend = RecordingSimBackend()
    motion = MotionController(backend, ServiceState(), conversation_motion=True, threaded=False)
    client = TestClient(create_app(backend, run_presence_loop=False, motion=motion))
    token = motion.begin_conversation()
    motion.conversation_state(token, 1, EmbodimentState.LISTENING)
    client.post("/daemon/standby")
    assert backend.calls[:2] == ["stop", "standby"]
    motion.run_pending()  # the pending listening gesture was invalidated
    assert "play:listening" not in backend.calls
