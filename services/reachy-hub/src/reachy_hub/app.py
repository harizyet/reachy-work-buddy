"""reachy-hub: robot registry + proxy to reachy-embodiment + sessions.

Phase 4: register robots, read their state, list/trigger behaviours, and
keep a background heartbeat going per docs/adr/0004 ("reachy-hub pings this
periodically").

Phase 5: AgentSession per docs/adr/0002 — POST /messages normalizes an
inbound (user_id, channel, text) to a session and forwards a channel-agnostic
turn to companion-core; GET /sessions/{user_id} exposes session state
directly so channel continuity is observable, not just inferred from replies.

Phase 6: Desk/Office/Silent/Remote as a deterministic I/O policy per
docs/adr/0006-response-routing.md. PATCH /sessions/{user_id}/mode sets
interaction_mode; POST /messages includes the resulting delivery_channel,
computed by response_policy.resolve_delivery_channel from mode + active
channel alone — never from what companion-core replied.

Phase 7: Telegram as the first external channel per docs/plan.md's Phase 7
row. A long-polling bot (telegram_client.py) turns inbound Telegram messages
into the exact same InboundMessage/handle_inbound_message path POST
/messages uses, and sends the reply back over Telegram when
delivery_channel resolves to it. Text only — voice notes are explicitly
deferred to Phase 8 (see telegram_client.py). Single-user: every inbound
Telegram message resolves to `telegram_default_user_id`, matching this
project's V0.1 scope (a personal assistant, not multi-tenant); see
telegram_chat_registry.py.

WebRTC, web UI, and auth (reachy-hub's full ADR 0001 ownership) are later
phases (15) — not implemented yet.

Per ADR 0003 ("Sent by companion-core (via reachy-hub) to
reachy-embodiment's POST /behaviour/{name}"), reachy-hub is the service that
actually holds the network path/credentials to each robot; companion-core
never talks to reachy-embodiment directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
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
from reachy_hub.postgres_telegram_chat_registry import PostgresTelegramChatRegistry
from reachy_hub.response_policy import resolve_delivery_channel
from reachy_hub.robot_registry import Robot, RobotRegistry
from reachy_hub.session_store import SessionStore
from reachy_hub.telegram_chat_registry import TelegramChatRegistry
from reachy_hub.telegram_client import TelegramClient
from shared.models.session import AgentSession, Channel, InteractionMode

log = logging.getLogger(__name__)


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
    delivery_channel: Channel
    reply: str


class SetModeRequest(BaseModel):
    interaction_mode: InteractionMode


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
    telegram_client: TelegramClient | None = None,
    telegram_bot_token: str | None = None,
    telegram_chat_registry: TelegramChatRegistry | None = None,
    telegram_default_user_id: str | None = None,
    run_telegram_poll_task: bool = True,
) -> FastAPI:
    client_factory = client_factory or (lambda base_url: EmbodimentClient(base_url))
    clients: dict[str, EmbodimentClient] = {}
    companion_core_client = companion_core_client or CompanionCoreClient(
        companion_core_base_url or os.environ.get("COMPANION_CORE_URL", "http://companion-core:8000")
    )

    # Telegram is optional: no token (env or explicit) means no client, no
    # polling, and no Postgres connection for the chat registry either —
    # reachy-hub degrades gracefully to Reachy-only, matching every other
    # optional integration in this system.
    telegram_bot_token = telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    owns_telegram_client = telegram_client is None and telegram_bot_token is not None
    if owns_telegram_client:
        telegram_client = TelegramClient(telegram_bot_token)
    telegram_enabled = telegram_client is not None
    telegram_default_user_id = telegram_default_user_id or os.environ.get(
        "TELEGRAM_DEFAULT_USER_ID", "default-user"
    )
    owns_telegram_chat_registry = telegram_chat_registry is None and telegram_enabled

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

    async def telegram_poll_loop(client: TelegramClient, chat_registry: TelegramChatRegistry, default_user_id: str) -> None:
        # Real Telegram blocks server-side for `timeout` seconds when idle,
        # which is what normally paces this loop. That's not guaranteed for
        # every server/proxy in between, so this loop enforces its own
        # minimum idle delay too — without it, a fast-responding server (or
        # a test's fake one) turns this into a tight busy-loop.
        idle_delay = 1.0
        offset: int | None = None
        while True:
            try:
                updates = await client.get_updates(offset=offset, timeout=25)
            except httpx.HTTPError:
                log.warning("telegram getUpdates failed, retrying in 2s", exc_info=True)
                await asyncio.sleep(2.0)
                continue

            if not updates:
                await asyncio.sleep(idle_delay)

            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message or "text" not in message:
                    continue  # voice notes and other non-text updates: Phase 8

                chat_id = message["chat"]["id"]
                await chat_registry.set_chat_id(default_user_id, chat_id)

                response = await handle_inbound_message(
                    InboundMessage(user_id=default_user_id, channel=Channel.TELEGRAM, text=message["text"])
                )
                # Always reply on the channel the question was asked on —
                # that's basic chat-bot UX, independent of delivery_channel.
                # delivery_channel (ADR 0006) governs where to push content
                # that doesn't already have an originating channel (e.g. a
                # future proactive notification); it deliberately does not
                # gate a direct reply to a direct message. Discovered while
                # building this: a fresh session defaults to Desk mode,
                # whose delivery_channel is always "reachy" — gating on it
                # here would silently drop the very first reply to anyone
                # who messages the bot before ever using Reachy.
                with contextlib.suppress(httpx.HTTPError):
                    await client.send_message(chat_id, response.reply)

    owns_registry = registry is None
    owns_session_store = session_store is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # An injected registry/session_store/telegram_chat_registry (tests)
        # is already set as app.state.* below, outside lifespan, so it's
        # usable even without startup/shutdown events running (e.g. a bare
        # httpx.ASGITransport). Only the Postgres-backed defaults need an
        # async connect at startup.
        if owns_registry:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.registry = await PostgresRobotRegistry.connect(dsn)
        if owns_session_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.session_store = await PostgresSessionStore.connect(dsn)
        if owns_telegram_chat_registry:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.telegram_chat_registry = await PostgresTelegramChatRegistry.connect(dsn)

        heartbeat_task = (
            asyncio.create_task(heartbeat_loop(app.state.registry, heartbeat_interval))
            if run_heartbeat_task
            else None
        )
        telegram_task = (
            asyncio.create_task(
                telegram_poll_loop(telegram_client, app.state.telegram_chat_registry, telegram_default_user_id)
            )
            if telegram_client is not None and run_telegram_poll_task
            else None
        )
        try:
            yield
        finally:
            for task in (heartbeat_task, telegram_task):
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            for client in clients.values():
                await client.aclose()
            await companion_core_client.aclose()
            if owns_telegram_client and telegram_client is not None:
                await telegram_client.aclose()
            if owns_registry:
                await app.state.registry.close()
            if owns_session_store:
                await app.state.session_store.close()
            if owns_telegram_chat_registry:
                await app.state.telegram_chat_registry.close()

    app = FastAPI(title="reachy-hub", lifespan=lifespan)
    if not owns_registry:
        app.state.registry = registry
    if not owns_session_store:
        app.state.session_store = session_store
    if not owns_telegram_chat_registry:
        app.state.telegram_chat_registry = telegram_chat_registry

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

    @app.patch("/sessions/{user_id}/mode")
    async def set_session_mode(user_id: str, request: SetModeRequest) -> AgentSession:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")
        return await app.state.session_store.set_mode(session, request.interaction_mode)

    async def handle_inbound_message(message: InboundMessage) -> MessageResponse:
        """Shared by POST /messages and the Telegram poll loop — the same
        normalization path regardless of which channel a message arrived
        on, per ADR 0002."""
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
            delivery_channel=resolve_delivery_channel(session.interaction_mode, session.active_channel),
            reply=result["reply"],
        )

    @app.post("/messages")
    async def post_message(message: InboundMessage) -> MessageResponse:
        return await handle_inbound_message(message)

    return app
