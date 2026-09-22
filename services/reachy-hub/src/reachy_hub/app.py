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

Phase 8: modular speech stack per docs/plan.md's Phase 8 row and §8's
deployment table ("STT | Homelab initially", "TTS | Cloud initially...
pluggable"). POST /voice/turn accepts a WAV recording, transcribes it
(stt.py, faster-whisper), runs it through the exact same
handle_inbound_message path every other channel uses (channel=reachy), and
synthesizes the reply (tts.py) back to WAV. No cloud TTS key is available,
so the concrete provider is a real local engine (espeak-ng) behind the same
TextToSpeech protocol a cloud provider would implement later — see tts.py.
STT/TTS providers are constructed lazily on first use, not at app startup,
so services that never touch voice pay no model-loading cost.

Phase 9: privacy/response router per ADR 0006's Consequences section and
docs/plan.md §9 ("Implement response metadata, deterministic routing, audit
events"). companion-core now proposes a `Privacy` classification per turn;
response_policy.apply_privacy_override enforces it — a response classified
sensitive/work-private can never be spoken aloud via Reachy, regardless of
mode, overriding whatever resolve_delivery_channel (Phase 6) would
otherwise have chosen. This is deliberately a *second* function, not a
modification of resolve_delivery_channel, which stays exactly as narrow as
Phase 6 made it (see response_policy.py). Every routing decision is
recorded via audit_log.py; GET /audit/{user_id} exposes it.

Phase 10: calendar reminder routing, per docs/plan.md's Phase 10 row
("later reminders route appropriately"). POST /calendar/check-reminders/{user_id}
pulls due reminders from companion-core (companion_core_client.due_reminders)
and runs each through the exact same resolve_delivery_channel +
apply_privacy_override + audit_log pipeline POST /messages uses — no new
routing logic, no background scheduler (that's proactive-notification
infrastructure explicitly scoped to Phases 17-18, not this one). If the
routed channel is Telegram and a chat_id is already known, the reminder is
actually delivered; otherwise the routing decision is still computed,
audited, and returned so it's observable even without a live delivery path.

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
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from reachy_hub.audit_log import AuditEntry, AuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.postgres_audit_log import PostgresAuditLog
from reachy_hub.postgres_registry import PostgresRobotRegistry
from reachy_hub.postgres_session_store import PostgresSessionStore
from reachy_hub.postgres_telegram_chat_registry import PostgresTelegramChatRegistry
from reachy_hub.response_policy import apply_privacy_override, resolve_delivery_channel
from reachy_hub.robot_registry import Robot, RobotRegistry
from reachy_hub.session_store import SessionStore
from reachy_hub.stt import FasterWhisperSTT, SpeechToText
from reachy_hub.telegram_chat_registry import TelegramChatRegistry
from reachy_hub.telegram_client import TelegramClient
from reachy_hub.tts import EspeakTTS, TextToSpeech
from shared.models.response import Privacy
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
    privacy: Privacy
    reply: str


class SetModeRequest(BaseModel):
    interaction_mode: InteractionMode


class ReminderRoutingResult(BaseModel):
    event_id: str
    text: str
    delivery_channel: Channel
    delivered: bool


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
    stt: SpeechToText | None = None,
    tts: TextToSpeech | None = None,
    stt_factory: Callable[[], SpeechToText] | None = None,
    tts_factory: Callable[[], TextToSpeech] | None = None,
    audit_log: AuditLog | None = None,
) -> FastAPI:
    client_factory = client_factory or (lambda base_url: EmbodimentClient(base_url))
    clients: dict[str, EmbodimentClient] = {}
    companion_core_client = companion_core_client or CompanionCoreClient(
        companion_core_base_url or os.environ.get("COMPANION_CORE_URL", "http://companion-core:8000")
    )

    # STT/TTS are constructed lazily, on first use — loading a Whisper
    # model is real work (seconds, plus a one-time download) that every
    # test/instance shouldn't pay for just to import this module.
    stt_factory = stt_factory or FasterWhisperSTT
    tts_factory = tts_factory or EspeakTTS
    voice_providers: dict[str, object] = {}
    if stt is not None:
        voice_providers["stt"] = stt
    if tts is not None:
        voice_providers["tts"] = tts

    def get_stt() -> SpeechToText:
        if "stt" not in voice_providers:
            voice_providers["stt"] = stt_factory()
        return voice_providers["stt"]  # type: ignore[return-value]

    def get_tts() -> TextToSpeech:
        if "tts" not in voice_providers:
            voice_providers["tts"] = tts_factory()
        return voice_providers["tts"]  # type: ignore[return-value]

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
    owns_audit_log = audit_log is None

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
        if owns_audit_log:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.audit_log = await PostgresAuditLog.connect(dsn)

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
            if owns_audit_log:
                await app.state.audit_log.close()

    app = FastAPI(title="reachy-hub", lifespan=lifespan)
    if not owns_registry:
        app.state.registry = registry
    if not owns_session_store:
        app.state.session_store = session_store
    if not owns_telegram_chat_registry:
        app.state.telegram_chat_registry = telegram_chat_registry
    if not owns_audit_log:
        app.state.audit_log = audit_log

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

    @app.get("/audit/{user_id}")
    async def get_audit_log(user_id: str, limit: int = 50) -> list[AuditEntry]:
        return await app.state.audit_log.list_for_user(user_id, limit=limit)

    @app.post("/calendar/check-reminders/{user_id}")
    async def check_reminders(user_id: str, within_minutes: int = 15) -> list[ReminderRoutingResult]:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")

        try:
            reminders = await companion_core_client.due_reminders(within_minutes=within_minutes)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"companion-core unreachable: {exc}") from exc

        results: list[ReminderRoutingResult] = []
        for reminder in reminders:
            privacy = Privacy(reminder["privacy"])
            base_channel = resolve_delivery_channel(session.interaction_mode, session.active_channel)
            delivery_channel = apply_privacy_override(base_channel, privacy, session.active_channel)

            await app.state.audit_log.record(
                user_id=user_id,
                session_id=session.session_id,
                channel=session.active_channel,
                mode=session.interaction_mode,
                privacy=privacy,
                base_channel=base_channel,
                delivery_channel=delivery_channel,
            )

            delivered = False
            if delivery_channel == Channel.TELEGRAM and telegram_client is not None:
                chat_id = await app.state.telegram_chat_registry.get_chat_id(user_id)
                if chat_id is not None:
                    with contextlib.suppress(httpx.HTTPError):
                        await telegram_client.send_message(chat_id, reminder["text"])
                        delivered = True

            results.append(
                ReminderRoutingResult(
                    event_id=reminder["event_id"],
                    text=reminder["text"],
                    delivery_channel=delivery_channel,
                    delivered=delivered,
                )
            )

        return results

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

        privacy = Privacy(result["privacy"])
        base_channel = resolve_delivery_channel(session.interaction_mode, session.active_channel)
        delivery_channel = apply_privacy_override(base_channel, privacy, session.active_channel)

        await app.state.audit_log.record(
            user_id=message.user_id,
            session_id=session.session_id,
            channel=message.channel,
            mode=session.interaction_mode,
            privacy=privacy,
            base_channel=base_channel,
            delivery_channel=delivery_channel,
        )

        return MessageResponse(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            active_channel=session.active_channel,
            delivery_channel=delivery_channel,
            privacy=privacy,
            reply=result["reply"],
        )

    @app.post("/messages")
    async def post_message(message: InboundMessage) -> MessageResponse:
        return await handle_inbound_message(message)

    @app.post("/voice/turn")
    async def voice_turn(user_id: str = Form(...), audio: UploadFile = File(...)) -> Response:  # noqa: B008
        wav_bytes = await audio.read()

        # faster-whisper and the espeak-ng subprocess are both blocking/
        # CPU-bound; running them inline would stall the event loop for
        # every other request while a transcription/synthesis is in flight.
        transcript = await asyncio.to_thread(get_stt().transcribe, wav_bytes)
        if not transcript:
            raise HTTPException(status_code=422, detail="no speech detected in audio")

        response = await handle_inbound_message(
            InboundMessage(user_id=user_id, channel=Channel.REACHY, text=transcript)
        )
        reply_wav = await asyncio.to_thread(get_tts().synthesize, response.reply)

        # Headers are the debugging/observability path (no client UI exists
        # yet to consume these) — ASCII-encoded defensively since HTTP
        # headers aren't safe for arbitrary text; this is a real limitation
        # for non-ASCII replies, not something Phase 8 needs to solve.
        return Response(
            content=reply_wav,
            media_type="audio/wav",
            headers={
                "X-Transcript": transcript.encode("ascii", errors="backslashreplace").decode("ascii"),
                "X-Reply-Text": response.reply.encode("ascii", errors="backslashreplace").decode("ascii"),
            },
        )

    return app
