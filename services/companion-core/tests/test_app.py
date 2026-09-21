"""companion-core tests, chained through real (in-process) reachy-hub and
reachy-embodiment apps via nested httpx.ASGITransport — proves the full
Phase 4 chain (companion-core -> reachy-hub -> reachy-embodiment) without
mocks or real sockets. Both sibling services are importable here only
because uv installs all workspace members into one shared dev venv.
"""

from collections.abc import Sequence

import httpx
from companion_core.app import create_app
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app as create_hub_app
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.robot_registry import InMemoryRobotRegistry, Robot


def make_chain(*, registered_robots: Sequence[Robot] = ()) -> TestClient:
    embodiment_app = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    registry = InMemoryRobotRegistry()
    registry._robots = {robot.robot_id: robot for robot in registered_robots}
    hub_app = create_hub_app(
        registry=registry,
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=False,
    )
    core_app = create_app(hub_base_url="http://reachy-hub", transport=httpx.ASGITransport(app=hub_app))
    return TestClient(core_app)


def test_health() -> None:
    with make_chain() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_debug_robot_state_returns_404_for_unregistered_robot() -> None:
    with make_chain() as client:
        resp = client.get("/debug/robots/desk-1/state")
        assert resp.status_code == 404


def test_debug_trigger_behaviour_reaches_reachy_embodiment_through_the_hub() -> None:
    # The robot is registered directly with reachy-hub, not through
    # companion-core: companion-core has no /robots endpoint of its own
    # (ADR 0001 — robot registry belongs to reachy-hub, not companion-core).
    robot = Robot(robot_id="desk-1", base_url="http://desk-1.local")
    with make_chain(registered_robots=[robot]) as client:
        resp = client.post("/debug/robots/desk-1/behaviour/greeting")
        assert resp.status_code == 200
        assert resp.json()["last_behaviour"] == "greeting"

        state_resp = client.get("/debug/robots/desk-1/state")
        assert state_resp.status_code == 200
        assert state_resp.json()["last_behaviour"] == "greeting"
