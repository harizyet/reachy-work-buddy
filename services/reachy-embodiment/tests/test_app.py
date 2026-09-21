from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app
from reachy_embodiment.robot import SimulatedRobotBackend

from shared.models.embodiment import Behaviour, EmbodimentState


def make_client() -> TestClient:
    return TestClient(create_app(SimulatedRobotBackend()))


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
        json={"behaviour_name": "greeting", "parameters": {"user": "hariz"}, "correlation_id": "abc-123"},
    )
    assert resp.status_code == 200
    assert resp.json()["last_behaviour"] == Behaviour.GREETING.value
