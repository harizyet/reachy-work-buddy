"""reachy-hub tests, chained against a real (in-process) reachy-embodiment
app via httpx.ASGITransport instead of mocks — this exercises the actual
request/response shapes across the service boundary. reachy_embodiment is a
sibling workspace member, importable here only because uv installs all
workspace members into one shared dev venv (see services/reachy-hub/README.md);
production reachy-hub images do not include reachy-embodiment's code.
"""

import time

import httpx
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.robot_registry import InMemoryRobotRegistry


def make_embodiment_app(**kwargs):
    return create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False, **kwargs)


def make_hub_client(embodiment_app, *, registry=None, **kwargs) -> TestClient:
    registry = registry or InMemoryRobotRegistry()
    app = create_app(
        registry=registry,
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=False,
        **kwargs,
    )
    return TestClient(app)


def test_health() -> None:
    client = make_hub_client(make_embodiment_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_and_list_robots() -> None:
    client = make_hub_client(make_embodiment_app())
    resp = client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})
    assert resp.status_code == 200

    resp = client.get("/robots")
    assert resp.json() == [{"robot_id": "desk-1", "base_url": "http://desk-1.local"}]


def test_unknown_robot_is_404() -> None:
    client = make_hub_client(make_embodiment_app())
    resp = client.get("/robots/nope/state")
    assert resp.status_code == 404


def test_robot_state_proxies_to_embodiment() -> None:
    client = make_hub_client(make_embodiment_app())
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.get("/robots/desk-1/state")
    assert resp.status_code == 200
    assert resp.json()["embodiment_state"] == "idle"


def test_robot_behaviours_proxies_the_catalogue() -> None:
    client = make_hub_client(make_embodiment_app())
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.get("/robots/desk-1/behaviours")
    assert resp.status_code == 200
    assert "listening" in resp.json()


def test_trigger_behaviour_proxies_and_updates_embodiment_state() -> None:
    client = make_hub_client(make_embodiment_app())
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.post("/robots/desk-1/behaviour/greeting")
    assert resp.status_code == 200
    assert resp.json()["last_behaviour"] == "greeting"

    resp = client.get("/robots/desk-1/state")
    assert resp.json()["last_behaviour"] == "greeting"


def test_trigger_unknown_behaviour_proxies_404_from_embodiment() -> None:
    client = make_hub_client(make_embodiment_app())
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.post("/robots/desk-1/behaviour/moonwalk")
    assert resp.status_code == 404


def test_heartbeat_background_task_pings_registered_robots() -> None:
    embodiment_app = make_embodiment_app()
    registry = InMemoryRobotRegistry()
    hub_app = create_app(
        registry=registry,
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=True,
        heartbeat_interval=0.05,
    )

    with TestClient(hub_app) as client:  # __enter__ runs lifespan, starting the heartbeat task
        client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})
        time.sleep(0.2)

    assert embodiment_app.state.service_state.last_heartbeat_at is not None
