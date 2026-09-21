"""reachy-embodiment: semantic behaviour HTTP API.

Implements the GET /health, GET /state, GET /behaviours, POST /behaviour/{name}
contract from docs/adr/0003-embodiment-command-api.md. /gaze, /pose, and
/audio/play are part of that ADR's full contract but have no real
implementation to back them yet (motion primitives land with the presence
loop in Phase 3, audio playback in a later phase) — they're left out here
rather than stubbed, to avoid dead endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from reachy_embodiment.behaviours import DESCRIPTIONS, STATE_FOR_BEHAVIOUR
from reachy_embodiment.robot import RobotBackend, SimulatedRobotBackend
from reachy_embodiment.state import ServiceState
from shared.models.embodiment import Behaviour, EmbodimentCommand
from shared.protocols import embodiment_api as routes


def create_app(backend: RobotBackend | None = None) -> FastAPI:
    backend = backend or SimulatedRobotBackend()
    state = ServiceState(connected=backend.connected, sim=backend.sim)

    app = FastAPI(title="reachy-embodiment")
    app.state.backend = backend
    app.state.service_state = state

    @app.get(routes.HEALTH)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(routes.STATE)
    def get_state() -> ServiceState:
        return state

    @app.get(routes.BEHAVIOURS)
    def list_behaviours() -> dict[str, str]:
        return {b.value: desc for b, desc in DESCRIPTIONS.items()}

    @app.post(routes.BEHAVIOUR)
    def trigger_behaviour(name: str, command: EmbodimentCommand | None = None) -> ServiceState:
        try:
            behaviour = Behaviour(name)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"unknown behaviour '{name}'")

        parameters = command.parameters if command else {}
        backend.play_behaviour(behaviour, parameters)

        state.last_behaviour = behaviour
        state.last_behaviour_at = datetime.now(UTC)
        if behaviour in STATE_FOR_BEHAVIOUR:
            state.embodiment_state = STATE_FOR_BEHAVIOUR[behaviour]

        return state

    return app


app = create_app()
