"""reachy-hub: robot registry + proxy to reachy-embodiment + sessions.

Phase 4: register robots, read their state, list/trigger behaviours, and
keep a background heartbeat going per docs/adr/0004 ("reachy-hub pings this
periodically").

Phase 5: AgentSession per docs/adr/0002 — POST /messages normalizes an
inbound (user_id, channel, text) to a session and forwards a channel-agnostic
turn to companion-core; GET /sessions/{user_id} exposes session state
directly so channel continuity is observable, not just inferred from replies.

Telegram, WebRTC, web UI, and auth (reachy-hub's full ADR 0001 ownership)
are later phases (6-7, 15) — not implemented yet.

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

from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.postgres_registry import PostgresRobotRegistry
from reachy_hub.postgres_session_store import PostgresSessionStore
from reachy_hub.robot_registry import Robot, RobotRegistry
from reachy_hub.session_store import SessionStore
from shared.models.session import AgentSession, Channel


class BehaviourRequest(BaseModel):
    parameters: dict[str, str] = {}
    correlation_id: str | None = None


class InboundMessage(BaseModel):
    user_id: str
    channel: Channel
    text: str


class MessageResponse(BaseModel):
    session_id: str
    conversation_id: str
    active_channel: Channel
    reply: str


def create_app(
    *,
    registry: RobotRegistry | None = None,
    session_store: SessionStore | None = None,
    database_url: str | None = None,
    client_factory: Callable[[str], EmbodimentClient] | None = None,
    companion_core_client: CompanionCoreClient | None = None,
    companion_core_base_url: str | None = None,
    run_heartbeat_task: bool = True,
    heartbeat_interval: float = 2.0,
) -> FastAPI:
    client_factory = client_factory or (lambda base_url: EmbodimentClient(base_url))
    clients: dict[str, EmbodimentClient] = {}
    companion_core_client = companion_core_client or CompanionCoreClient(
        companion_core_base_url or os.environ.get("COMPANION_CORE_URL", "http://companion-core:8000")
    )

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
    owns_session_store = session_store is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # An injected registry/session_store (tests) is already set as
        # app.state.* below, outside lifespan, so it's usable even without
        # startup/shutdown events running (e.g. a bare httpx.ASGITransport).
        # Only the Postgres-backed defaults need an async connect at startup.
        if owns_registry:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.registry = await PostgresRobotRegistry.connect(dsn)
        if owns_session_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.session_store = await PostgresSessionStore.connect(dsn)

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
            await companion_core_client.aclose()
            if owns_registry:
                await app.state.registry.close()
            if owns_session_store:
                await app.state.session_store.close()

    app = FastAPI(title="reachy-hub", lifespan=lifespan)
    if not owns_registry:
        app.state.registry = registry
    if not owns_session_store:
        app.state.session_store = session_store

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

    @app.get("/sessions/{user_id}")
    async def get_session(user_id: str) -> AgentSession:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")
        return session

    @app.post("/messages")
    async def post_message(message: InboundMessage) -> MessageResponse:
        session = await app.state.session_store.get_or_create(message.user_id, message.channel)
        if session.active_channel != message.channel:
            session = await app.state.session_store.touch_channel(session, message.channel)

        try:
            result = await companion_core_client.send_turn(
                session.session_id, session.conversation_id, message.channel.value, message.text
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"companion-core unreachable: {exc}") from exc

        return MessageResponse(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            active_channel=session.active_channel,
            reply=result["reply"],
        )

    return app
