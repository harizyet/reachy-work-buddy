"""reachy-embodiment: semantic behaviour HTTP API + local presence loop.

Implements the GET /health, GET /state, GET /behaviours, POST /behaviour/{name}
contract from docs/adr/0003-embodiment-command-api.md, plus POST /heartbeat
and the offline-fallback presence loop from docs/adr/0004-offline-fallback.md.
/gaze, /pose, and /audio/play are part of the ADR 0003 contract but have no
real implementation to back them yet (motion primitives land with real
hardware, audio playback in a later phase) — they're left out here rather
than stubbed, to avoid dead endpoints.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from reachy_embodiment.behaviours import DESCRIPTIONS, STATE_FOR_BEHAVIOUR
from reachy_embodiment.presence import PresenceLoop
from reachy_embodiment.robot import RobotBackend, SimulatedRobotBackend
from reachy_embodiment.state import ServiceState
from shared.models.embodiment import Behaviour, EmbodimentCommand
from shared.protocols import embodiment_api as routes


def create_app(backend: RobotBackend | None = None, *, run_presence_loop: bool = True) -> FastAPI:
    backend = backend or SimulatedRobotBackend()
    state = ServiceState(connected=backend.connected, sim=backend.sim)
    presence_loop = PresenceLoop(backend, state)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if run_presence_loop:
            presence_loop.start()
        try:
            yield
        finally:
            if run_presence_loop:
                presence_loop.stop()

    app = FastAPI(title="reachy-embodiment", lifespan=lifespan)
    app.state.backend = backend
    app.state.service_state = state
    app.state.presence_loop = presence_loop

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

        # A command from companion-core (via reachy-hub) is itself proof the
        # homelab is reachable, so it counts as a heartbeat too.
        presence_loop.heartbeat()

        parameters = command.parameters if command else {}
        backend.play_behaviour(behaviour, parameters)

        state.last_behaviour = behaviour
        state.last_behaviour_at = datetime.now(UTC)
        if behaviour in STATE_FOR_BEHAVIOUR:
            state.embodiment_state = STATE_FOR_BEHAVIOUR[behaviour]

        return state

    @app.post(routes.HEARTBEAT)
    def heartbeat() -> ServiceState:
        presence_loop.heartbeat()
        return state

    return app


app = create_app()
