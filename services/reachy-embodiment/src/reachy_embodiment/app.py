"""reachy-embodiment: semantic behaviour HTTP API + local presence loop.

Implements the GET /health, GET /state, GET /behaviours, POST /behaviour/{name}
contract from docs/adr/0003-embodiment-command-api.md, plus POST /heartbeat
and the offline-fallback presence loop from docs/adr/0004-offline-fallback.md.

Phase 16/ADR 0013 (remote telepresence) implements two of the three
previously-deferred ADR 0003 endpoints: GET /camera/frame (a single JPEG,
polled by reachy-hub's WebRTC video track) and POST /audio/play (plays a
WAV through the robot's speaker — or logs it, no physical speaker exists in
this environment, see robot.py). /gaze and /pose remain deferred — no motion
primitives exist to back them without real hardware, still left out rather
than stubbed, to avoid dead endpoints. POST /remote is new (not part of ADR
0003's original list): reachy-hub calls it to mark a telepresence session's
start/end, driving the long-unused EmbodimentState.REMOTE.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from reachy_embodiment.behaviours import DESCRIPTIONS, STATE_FOR_BEHAVIOUR
from reachy_embodiment.presence import PresenceLoop
from reachy_embodiment.robot import (
    ReachyDaemonBackend,
    RobotBackend,
    SimulatedRobotBackend,
)
from reachy_embodiment.robot_ws_client import RobotWSClient
from reachy_embodiment.state import ServiceState
from shared.models.embodiment import Behaviour, EmbodimentState
from shared.protocols import embodiment_api as routes

log = logging.getLogger(__name__)


def _default_backend() -> RobotBackend:
    """Selects the backend from `ROBOT_BACKEND`/`REACHY_DAEMON_URL`.

    Deliberately does not fall back to SimulatedRobotBackend on a bad/
    unrecognized ROBOT_BACKEND value — Phase 22's plan requires real mode
    to fail clearly rather than silently behave like simulation. Defaults
    to simulated only when the variable is entirely unset, matching every
    prior phase's behaviour before this one existed.
    """
    kind = os.environ.get("ROBOT_BACKEND", "simulated").strip().lower()
    if kind in ("simulated", "sim"):
        return SimulatedRobotBackend()
    if kind in ("reachy_daemon", "reachy-daemon", "real"):
        daemon_url = os.environ.get("REACHY_DAEMON_URL", "http://127.0.0.1:8000")
        return ReachyDaemonBackend(daemon_url)
    raise ValueError(f"unknown ROBOT_BACKEND {kind!r}; expected 'simulated' or 'reachy_daemon'")


def _default_robot_ws_client(backend: RobotBackend) -> RobotWSClient | None:
    """Builds the ADR 0019 WS client from `HUB_WS_URL`/`ROBOT_ID`/
    `ROBOT_TOKEN`. Returns None (no outbound connection attempted) unless
    all three are set — this is additive to the HTTP dev/simulation
    workflow, not a requirement for it; a dev instance with none of these
    set behaves exactly as every prior phase did.
    """
    hub_ws_url = os.environ.get("HUB_WS_URL")
    robot_id = os.environ.get("ROBOT_ID")
    robot_token = os.environ.get("ROBOT_TOKEN")
    if not (hub_ws_url and robot_id and robot_token):
        return None
    return RobotWSClient(hub_ws_url, robot_id, robot_token, sim=backend.sim)


class BehaviourBody(BaseModel):
    """Body for POST /behaviour/{name}.

    Deliberately excludes behaviour_name: the URL path is the single source
    of truth for which behaviour is being triggered. Duplicating it in the
    body (as shared.models.embodiment.EmbodimentCommand does for the
    conceptual companion-core -> reachy-hub payload) invites a body/path
    mismatch, which previously surfaced as a body-validation 422 instead of
    the path-driven 404 an unknown behaviour name should produce.
    """

    parameters: dict[str, str] = {}
    correlation_id: str | None = None


class RemoteBody(BaseModel):
    active: bool


def create_app(
    backend: RobotBackend | None = None,
    *,
    run_presence_loop: bool = True,
    robot_ws_client: RobotWSClient | None = None,
    run_robot_ws_client: bool = True,
) -> FastAPI:
    backend = backend or _default_backend()
    state = ServiceState(connected=backend.connected, sim=backend.sim)
    presence_loop = PresenceLoop(backend, state)
    if robot_ws_client is None and run_robot_ws_client:
        robot_ws_client = _default_robot_ws_client(backend)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if run_presence_loop:
            presence_loop.start()
        ws_task: asyncio.Task[None] | None = None
        if robot_ws_client is not None and run_robot_ws_client:
            ws_task = asyncio.create_task(robot_ws_client.run())
        try:
            yield
        finally:
            if run_presence_loop:
                presence_loop.stop()
            if ws_task is not None:
                ws_task.cancel()
                try:
                    await ws_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    log.exception("robot WS client task raised during shutdown")

    app = FastAPI(title="reachy-embodiment", lifespan=lifespan)
    app.state.backend = backend
    app.state.service_state = state
    app.state.presence_loop = presence_loop
    app.state.robot_ws_client = robot_ws_client

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
    def trigger_behaviour(name: str, body: BehaviourBody | None = None) -> ServiceState:
        try:
            behaviour = Behaviour(name)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"unknown behaviour '{name}'")

        # A command from companion-core (via reachy-hub) is itself proof the
        # homelab is reachable, so it counts as a heartbeat too.
        presence_loop.heartbeat()

        parameters = body.parameters if body else {}
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

    @app.get(routes.CAMERA_FRAME)
    def camera_frame() -> Response:
        presence_loop.heartbeat()
        return Response(content=backend.capture_frame(), media_type="image/jpeg")

    @app.post(routes.REMOTE)
    def set_remote(body: RemoteBody) -> ServiceState:
        presence_loop.heartbeat()
        state.remote_active = body.active
        state.embodiment_state = EmbodimentState.REMOTE if body.active else EmbodimentState.IDLE
        return state

    @app.post(routes.AUDIO_PLAY)
    async def audio_play(audio: UploadFile = File(...)) -> ServiceState:  # noqa: B008
        wav_bytes = await audio.read()
        presence_loop.heartbeat()

        state.embodiment_state = EmbodimentState.SPEAKING
        state.last_behaviour = Behaviour.SPEAKING
        state.last_behaviour_at = datetime.now(UTC)

        backend.play_audio(wav_bytes)

        # No physical speaker blocks for real playback time here (see
        # robot.py), so there's nothing to schedule a revert against — it
        # happens synchronously within this same request, same as every
        # other state transition in this module.
        state.embodiment_state = EmbodimentState.REMOTE if state.remote_active else EmbodimentState.IDLE
        return state

    return app


app = create_app()
