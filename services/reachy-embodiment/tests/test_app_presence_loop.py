"""Integration proof of Phase 3's exit criterion at the HTTP layer: the real
FastAPI app, started the way uvicorn would start it (lifespan on), keeps
animating on its own and falls back to DISCONNECTED without any client ever
calling anything other than GET /state.
"""

import time

from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app
from reachy_embodiment.robot import SimulatedRobotBackend

from shared.models.embodiment import EmbodimentState


def test_app_animates_autonomously_and_falls_back_when_homelab_stops() -> None:
    backend = SimulatedRobotBackend()
    app = create_app(backend, run_presence_loop=True)
    app.state.presence_loop._heartbeat_timeout = 0.1
    app.state.presence_loop._idle_cycle_seconds = 0.05

    with TestClient(app) as client:  # __enter__ runs the lifespan, starting the presence loop
        time.sleep(0.08)
        first = client.get("/state").json()
        assert first["last_behaviour"] is not None
        assert first["embodiment_state"] == EmbodimentState.IDLE.value

        # No heartbeat and no behaviour command sent — homelab is effectively "down".
        time.sleep(0.15)
        disconnected = client.get("/state").json()
        assert disconnected["embodiment_state"] == EmbodimentState.DISCONNECTED.value
        assert disconnected["last_behaviour"] is not None  # still animating

        time.sleep(0.1)
        still_animating = client.get("/state").json()
        assert still_animating["last_behaviour_at"] != first["last_behaviour_at"]

        # Homelab comes back.
        recovered = client.post("/heartbeat").json()
        assert recovered["embodiment_state"] == EmbodimentState.IDLE.value
