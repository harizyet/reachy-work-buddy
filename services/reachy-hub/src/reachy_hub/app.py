"""reachy-hub: robot registry + proxy to reachy-embodiment.

Phase 4 scope only: register robots, read their state, list/trigger
behaviours, and keep a background heartbeat going per docs/adr/0004
("reachy-hub pings this periodically"). Sessions, Telegram, WebRTC, web UI,
and auth (reachy-hub's full ADR 0001 ownership) are later phases (5-7, 15) —
this is the minimal slice needed for Phase 4's exit criterion: "Homelab can
invoke Reachy behaviours and read status."

Per ADR 0003 ("Sent by companion-core (via reachy-hub) to
reachy-embodiment's POST /behaviour/{name}"), reachy-hub is the service that
actually holds the network path/credentials to each robot; companion-core
never talks to reachy-embodiment directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.postgres_registry import PostgresRobotRegistry
from reachy_hub.robot_registry import Robot, RobotRegistry


class BehaviourRequest(BaseModel):
    parameters: dict[str, str] = {}
    correlation_id: str | None = None


def create_app(
    *,
    registry: RobotRegistry | None = None,
    database_url: str | None = None,
    client_factory: Callable[[str], EmbodimentClient] | None = None,
    run_heartbeat_task: bool = True,
    heartbeat_interval: float = 2.0,
) -> FastAPI:
    client_factory = client_factory or (lambda base_url: EmbodimentClient(base_url))
    clients: dict[str, EmbodimentClient] = {}

    def get_client(robot: Robot) -> EmbodimentClient:
        client = clients.get(robot.robot_id)
        if client is None:
            client = client_factory(robot.base_url)
            clients[robot.robot_id] = client
        return client

    # interval must stay comfortably below reachy-embodiment's
    # PresenceLoop.heartbeat_timeout (default 5.0s in presence.py) or
    # ordinary network jitter trips a false DISCONNECTED. Default here (2.0s)
    # leaves 2.5x margin.
    async def heartbeat_loop(reg: RobotRegistry, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            for robot in await reg.list():
                with contextlib.suppress(httpx.HTTPError):
                    await get_client(robot).heartbeat()

    owns_registry = registry is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # An injected registry (tests) is already set as app.state.registry
        # below, outside lifespan, so it's usable even without startup/
        # shutdown events running (e.g. a bare httpx.ASGITransport). Only the
        # Postgres-backed default needs an async connect at startup.
        if owns_registry:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.registry = await PostgresRobotRegistry.connect(dsn)

        heartbeat_task = (
            asyncio.create_task(heartbeat_loop(app.state.registry, heartbeat_interval))
            if run_heartbeat_task
            else None
        )
        try:
            yield
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            for client in clients.values():
                await client.aclose()
            if owns_registry:
                await app.state.registry.close()

    app = FastAPI(title="reachy-hub", lifespan=lifespan)
    if not owns_registry:
        app.state.registry = registry

    async def get_robot_or_404(robot_id: str) -> Robot:
        robot = await app.state.registry.get(robot_id)
        if robot is None:
            raise HTTPException(status_code=404, detail=f"unknown robot '{robot_id}'")
        return robot

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/robots")
    async def register_robot(robot: Robot) -> Robot:
        await app.state.registry.register(robot)
        return robot

    @app.get("/robots")
    async def list_robots() -> list[Robot]:
        return await app.state.registry.list()

    @app.get("/robots/{robot_id}/state")
    async def robot_state(robot_id: str) -> dict:
        robot = await get_robot_or_404(robot_id)
        try:
            return await get_client(robot).get_state()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"robot '{robot_id}' unreachable: {exc}") from exc

    @app.get("/robots/{robot_id}/behaviours")
    async def robot_behaviours(robot_id: str) -> dict:
        robot = await get_robot_or_404(robot_id)
        try:
            return await get_client(robot).list_behaviours()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"robot '{robot_id}' unreachable: {exc}") from exc

    @app.post("/robots/{robot_id}/behaviour/{name}")
    async def trigger_robot_behaviour(robot_id: str, name: str, request: BehaviourRequest | None = None) -> dict:
        robot = await get_robot_or_404(robot_id)
        request = request or BehaviourRequest()
        try:
            return await get_client(robot).trigger_behaviour(
                name, parameters=request.parameters, correlation_id=request.correlation_id
            )
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"robot '{robot_id}' unreachable: {exc}") from exc

    return app
