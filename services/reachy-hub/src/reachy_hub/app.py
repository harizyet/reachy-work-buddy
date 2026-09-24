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

ADR 0011 (destructive-action consent, a cross-cutting safety refactor
inserted ahead of Phase 15): `InboundMessage`/`MessageResponse` now carry
`input_modality` — only `POST /voice/turn` ever sets it to `VOICE`,
everything else defaults to `TEXT` — threaded through to companion-core so
it can refuse to accept a destructive-action confirmation that arrived as
voice, regardless of what it transcribes to. reachy-hub does no
enforcement itself here (companion-core's consent/ module does, since
that's where the destructive tools/stores live); reachy-hub's only job is
not losing the signal in transit.

Phase 15: "Call Reachy" — real WebRTC audio between clients/web-pwa/ and
`POST /webrtc/offer` (webrtc.py), push-to-talk turn-taking over a
"control" RTCDataChannel (see webrtc.py's module docstring for why not
continuous VAD), reusing the exact same STT/TTS providers and
`handle_inbound_message` path every other channel uses —
`InboundMessage(channel=Channel.WEB, input_modality=InputModality.VOICE)`.
Each turn triggers the robot's real `listening`/`thinking`/`speaking`
behaviours (already in `Behaviour`'s vocabulary, ADR 0003) through the
existing `EmbodimentClient`, synchronized with the actual reply audio,
which only ever flows back over the peer connection — never through
Reachy's speaker, which doesn't exist as a code path here at all (no
physical Reachy in this environment, same as every other voice-touching
phase).

Phase 16 (remote telepresence, ADR 0013): reachy-hub's first real
authentication — a shared bearer token (`REMOTE_UI_TOKEN`), checked by
`require_remote_auth` and applied to the whole remote-control surface
(`/robots/{robot_id}/state`, `/behaviours`, `/behaviour/{name}`, plus the
two new routes below). Fails *closed*: an unset token 503s every gated
route rather than allowing unauthenticated access, the opposite default
from every other optional integration here — see ADR 0013 for why.
`POST /robots/{robot_id}/speak` synthesizes text with the same local
`tts.py` `/voice/turn` uses and plays it through the robot via
`EmbodimentClient.play_audio` — no `companion_core_client` call anywhere
in that path, which is what satisfies the phase's "without Companion
Core" exit criterion. `POST /webrtc/telepresence/offer`
(`webrtc.negotiate_telepresence`) streams the robot's camera to the
browser over a second, unrelated `RTCPeerConnection` from "Call Reachy"'s
— video-only, no reasoning, no audio.

Per ADR 0003 ("Sent by companion-core (via reachy-hub) to
reachy-embodiment's POST /behaviour/{name}"), reachy-hub is the service that
actually holds the network path/credentials to each robot; companion-core
never talks to reachy-embodiment directly.

Phase 18 (daily briefing, ADR 0015): `POST /briefing/{user_id}` combines
companion-core's calendar/tasks/email/reminders/project-events
(`companion_core.briefing.build_briefing`, exposed as `GET /briefing`) into
one prioritized list. "Reachy greets" is an unconditional arrival gesture
(`Behaviour.GREETING`) — the detailed text is routed through the exact same
`resolve_delivery_channel`/`apply_privacy_override`/`decide_action` pipeline
`POST /calendar/check-reminders/{user_id}` (Phase 17) uses, forced
`Privacy.WORK_PRIVATE` so it can never land on Reachy's speaker — the
literal mechanism behind "detailed briefing is privately delivered". No new
storage: it reuses `notification_queue`/`audit_log` exactly as they already
exist.

Phase 24c (ADR 0023): robot microphone conversation lives in robot_voice.py.
This module only adapts its existing STT/TTS, handle_inbound_message and
Telegram push into that module's pipeline, and wires the WSS hooks and the
logout stop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from reachy_hub.audit_log import AuditEntry, AuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.interruption_policy import (
    decide_action,
    downgrade_for_presence,
    is_occupied,
)
from reachy_hub.notification_queue import NotificationQueue, QueuedNotification
from reachy_hub.operator import install_operator_routes, require_csrf
from reachy_hub.postgres_audit_log import PostgresAuditLog
from reachy_hub.postgres_notification_queue import PostgresNotificationQueue
from reachy_hub.postgres_registry import PostgresRobotRegistry
from reachy_hub.postgres_session_store import PostgresSessionStore
from reachy_hub.postgres_telegram_chat_registry import PostgresTelegramChatRegistry
from reachy_hub.response_policy import (
    apply_privacy_override,
    resolve_delivery_channel,
    robot_speech_withheld_reason,
)
from reachy_hub.robot_connection_manager import RobotConnectionManager
from reachy_hub.robot_credential_store import RobotCredentialStore
from reachy_hub.robot_credential_store import (
    load_from_env as load_robot_tokens_from_env,
)
from reachy_hub.robot_registry import Robot, RobotRegistry
from reachy_hub.robot_voice import (
    ConversationReply,
    RobotVoiceManager,
    VoiceTurnPipeline,
    install_robot_voice_routes,
    voice_watchdog_loop,
)
from reachy_hub.robot_ws import install_robot_ws_routes
from reachy_hub.session_store import SessionStore
from reachy_hub.stt import FasterWhisperSTT, SpeechToText
from reachy_hub.telegram_chat_registry import TelegramChatRegistry
from reachy_hub.telegram_client import TelegramClient
from reachy_hub.telegram_health import TelegramPollHealth, poll_updates
from reachy_hub.tts import EspeakTTS, TextToSpeech
from reachy_hub.user_store import PostgresUserStore, UserStore
from reachy_hub.webrtc import CallTurnHandler, negotiate_call, negotiate_telepresence
from shared.models.embodiment import Behaviour
from shared.models.interruption import InterruptionAction
from shared.models.response import Privacy, Urgency
from shared.models.session import (
    AgentSession,
    Channel,
    InputModality,
    InteractionMode,
    PrivacyContext,
)
from shared.protocols.operator_api import (
    ROBOT_VOICE,
    ROBOTS,
    ROBOTS_RESUME,
    ROBOTS_STANDBY,
)

log = logging.getLogger(__name__)


class BehaviourRequest(BaseModel):
    parameters: dict[str, str] = {}
    correlation_id: str | None = None


class InboundMessage(BaseModel):
    user_id: str
    channel: Channel
    text: str
    # docs/adr/0011 (destructive-action consent): only voice_turn (real STT)
    # ever sets VOICE.
    # Everything else — typed messages, Telegram — defaults to TEXT, which
    # is what makes destructive-action confirmation possible from voice at
    # all: it's always refused.
    input_modality: InputModality = InputModality.TEXT
    force_frontier: bool = False


class MessageResponse(BaseModel):
    session_id: str
    conversation_id: str
    active_channel: Channel
    delivery_channel: Channel
    privacy: Privacy
    reply: str


class SetModeRequest(BaseModel):
    interaction_mode: InteractionMode


class SetDndRequest(BaseModel):
    dnd: bool


class SetPrivacyContextRequest(BaseModel):
    privacy_context: PrivacyContext


class ReminderRoutingResult(BaseModel):
    event_id: str
    text: str
    delivery_channel: Channel
    action: InterruptionAction
    delivered: bool


class BriefingItemResult(BaseModel):
    category: str
    text: str
    privacy: Privacy
    urgency: Urgency


class BriefingDeliveryResult(BaseModel):
    greeted: bool
    items: list[BriefingItemResult]
    text: str
    delivery_channel: Channel
    action: InterruptionAction
    delivered: bool


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str
    user_id: str
    robot_id: str


class WebRTCAnswerResponse(BaseModel):
    sdp: str
    type: str


class SpeakRequest(BaseModel):
    text: str


class TelepresenceOfferRequest(BaseModel):
    sdp: str
    type: str
    robot_id: str


def create_app(
    *,
    accounts_service_token: str | None = None,
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
    notification_queue: NotificationQueue | None = None,
    remote_ui_token: str | None = None,
    user_store: UserStore | None = None,
    session_secret_key: str | None = None,
    admin_username: str | None = None,
    admin_password: str | None = None,
    session_cookie_secure: bool | None = None,
    robot_credential_store: RobotCredentialStore | None = None,
    robot_connection_manager: RobotConnectionManager | None = None,
    robot_ws_heartbeat_interval: float = 2.0,
    robot_ws_watchdog_timeout: float = 5.0,
    robot_voice_manager: RobotVoiceManager | None = None,
    run_voice_watchdog_task: bool = True,
) -> FastAPI:
    # Phase 16/ADR 0013: fail closed. Unset means the whole remote-control
    # surface below 503s rather than silently allowing unauthenticated
    # access — the opposite default from every other optional integration
    # in this file (Telegram, cloud TTS), deliberately: those degrade a
    # convenience by being absent, this gates real robot control exposed on
    # a port the Caddyfile itself documents as public-reachable.
    accounts_service_token = accounts_service_token or os.environ.get("ACCOUNTS_SERVICE_TOKEN")
    owner_user_id = os.environ.get("OWNER_USER_ID", "default-user")
    telegram_owner_chat = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    remote_ui_token = remote_ui_token or os.environ.get("REMOTE_UI_TOKEN") or None
    session_secret_key = session_secret_key or os.environ.get("SESSION_SECRET_KEY") or None
    admin_username = admin_username or os.environ.get("ADMIN_USERNAME") or None
    admin_password = admin_password or os.environ.get("ADMIN_PASSWORD") or None
    if session_cookie_secure is None:
        session_cookie_secure = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    owns_user_store = user_store is None and session_secret_key is not None

    async def require_remote_auth(request: Request, authorization: str | None = Header(default=None)) -> None:
        owner = await app.state.user_store.owner() if session_secret_key else None
        if not remote_ui_token and not owner:
            raise HTTPException(503, "Remote UI is not configured (set owner login or REMOTE_UI_TOKEN)")
        if authorization is not None:
            if (remote_ui_token and authorization.startswith("Bearer ")
                    and secrets.compare_digest(authorization.removeprefix("Bearer ").encode(), remote_ui_token.encode())):
                return
            raise HTTPException(401, "Invalid bearer token")
        if owner and request.scope.get("session", {}).get("user") == owner:
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                require_csrf(request)
            return
        raise HTTPException(401, "Authentication required")

    client_factory = client_factory or (lambda base_url: EmbodimentClient(base_url))
    clients: dict[str, EmbodimentClient] = {}
    companion_core_client = companion_core_client or CompanionCoreClient(
        companion_core_base_url or os.environ.get("COMPANION_CORE_URL", "http://companion-core:8000"),
        service_token=accounts_service_token
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

    # Construction can take tens of seconds (first-use model download), so
    # callers must reach these from a worker thread (transcribe/synthesize
    # below), never on the event loop: blocking the loop that long stalls
    # every other request and the robot WSS keepalive, which disconnected
    # the robot mid-turn in the Phase 24c Compose run. The lock stops two
    # first requests from loading two models.
    voice_provider_lock = threading.Lock()

    def get_stt() -> SpeechToText:
        with voice_provider_lock:
            if "stt" not in voice_providers:
                voice_providers["stt"] = stt_factory()
            return voice_providers["stt"]  # type: ignore[return-value]

    def get_tts() -> TextToSpeech:
        with voice_provider_lock:
            if "tts" not in voice_providers:
                voice_providers["tts"] = tts_factory()
            return voice_providers["tts"]  # type: ignore[return-value]

    def transcribe(wav_bytes: bytes) -> str:
        return get_stt().transcribe(wav_bytes)

    def synthesize(text: str) -> bytes:
        return get_tts().synthesize(text)

    # Telegram is optional: no token (env or explicit) means no client, no
    # polling, and no Postgres connection for the chat registry either —
    # reachy-hub degrades gracefully to Reachy-only, matching every other
    # optional integration in this system.
    telegram_bot_token = telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN") or None
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
                updates = await poll_updates(client, app.state.telegram_poll_health, offset=offset)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                log.warning("%s; retrying in 2s", app.state.telegram_poll_health.last_poll_error)
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
                if accounts_service_token and (
                    str(chat_id) != telegram_owner_chat or message["chat"].get("type") != "private"
                    or default_user_id != owner_user_id
                ):
                    continue
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
    owns_notification_queue = notification_queue is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if owns_session_store and not accounts_service_token:
            raise RuntimeError("ACCOUNTS_SERVICE_TOKEN is required for production data access")
        # An injected registry/session_store/telegram_chat_registry (tests)
        # is already set as app.state.* below, outside lifespan, so it's
        # usable even without startup/shutdown events running (e.g. a bare
        # httpx.ASGITransport). Only the Postgres-backed defaults need an
        # async connect at startup.
        if owns_user_store:
            app.state.user_store = await PostgresUserStore.connect(database_url or os.environ["DATABASE_URL"])
        if session_secret_key and admin_username and admin_password:
            await app.state.user_store.bootstrap(admin_username, admin_password)
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
        if owns_notification_queue:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.notification_queue = await PostgresNotificationQueue.connect(dsn)

        heartbeat_task = (
            asyncio.create_task(heartbeat_loop(app.state.registry, heartbeat_interval))
            if run_heartbeat_task
            else None
        )
        if telegram_client is not None and run_telegram_poll_task:
            # Phase 24b: registers the flat command aliases (Telegram's
            # BotCommand.command can't hold a space, so the namespaced
            # `/reachy <action>` form isn't registered here — see
            # companion_core/commands/parser.py's TELEGRAM_ALIASES).
            # Best-effort: a registration failure shouldn't block hub
            # startup, same as heartbeat_loop's tolerance below.
            with contextlib.suppress(httpx.HTTPError):
                await telegram_client.set_my_commands([
                    {"command": "standby", "description": "Put Reachy into standby"},
                    {"command": "wake", "description": "Wake Reachy up"},
                    {"command": "reachy_status", "description": "Check Reachy's status"},
                ])
        telegram_task = (
            asyncio.create_task(
                telegram_poll_loop(telegram_client, app.state.telegram_chat_registry, telegram_default_user_id)
            )
            if telegram_client is not None and run_telegram_poll_task
            else None
        )
        voice_task = (
            asyncio.create_task(voice_watchdog_loop(robot_voice_manager)) if run_voice_watchdog_task else None
        )
        try:
            yield
        finally:
            await robot_voice_manager.stop_all("Hub is shutting down")
            for task in (heartbeat_task, telegram_task, voice_task):
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            for pc in list(app.state.webrtc_connections):
                await pc.close()
            app.state.webrtc_connections.clear()
            for client in clients.values():
                await client.aclose()
            await companion_core_client.aclose()
            if owns_telegram_client and telegram_client is not None:
                await telegram_client.aclose()
            if owns_user_store:
                await app.state.user_store.close()
            if owns_registry:
                await app.state.registry.close()
            if owns_session_store:
                await app.state.session_store.close()
            if owns_telegram_chat_registry:
                await app.state.telegram_chat_registry.close()
            if owns_audit_log:
                await app.state.audit_log.close()
            if owns_notification_queue:
                await app.state.notification_queue.close()

    app = FastAPI(title="reachy-hub", lifespan=lifespan)
    app.state.telegram_poll_health = TelegramPollHealth()
    app.state.user_store = user_store
    from reachy_hub.accounts import install_accounts
    from shared.protocols.accounts import ACCOUNTS_CALLBACK

    install_accounts(app, companion_core_client, enabled=bool(accounts_service_token))

    @app.middleware("http")
    async def private_work_routes(request, call_next):
        from fastapi.responses import JSONResponse
        path = request.url.path
        work_path = path.startswith(("/sessions/", "/audit/", "/notifications/",
                                      "/calendar/", "/briefing/")) or path in {
            "/messages", "/voice/turn", "/webrtc/offer",
        }
        if accounts_service_token and work_path:
            try:
                await require_remote_auth(request, request.headers.get("Authorization"))
                if path.startswith(("/sessions/", "/audit/", "/notifications/", "/briefing/")):
                    selected = path.split("/")[2]
                elif path.startswith("/calendar/check-reminders/"):
                    selected = path.split("/")[3]
                elif request.method == "POST":
                    await request.body()
                    if path == "/voice/turn":
                        selected = (await request.form()).get("user_id")
                    else:
                        selected = (await request.json()).get("user_id")
                else:
                    selected = owner_user_id
                if selected != owner_user_id:
                    raise HTTPException(403, "This account belongs to the signed-in owner")
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            except (ValueError, KeyError):
                return JSONResponse(status_code=422, content={"detail": "Invalid request"})
        response = await call_next(request)
        if work_path or path.startswith(("/settings/accounts/", ROBOT_VOICE)):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        if path == ACCOUNTS_CALLBACK:
            request.scope["query_string"] = b""
        return response

    if session_secret_key:
        app.add_middleware(SessionMiddleware, secret_key=session_secret_key,
                           session_cookie="reachy_session", max_age=43200,
                           same_site="strict", https_only=session_cookie_secure)
    # ADR 0019 (Phase 22): robot-initiated WSS control connection.
    # robot_connection_manager is always process-local in-memory (never
    # restored across restarts, ADR 0019) — no env/Postgres wiring makes
    # sense for it, unlike every other app.state.* store above.
    # robot_credential_store defaults to ROBOT_TOKENS (see
    # robot_credential_store.py); unset means no robot can authenticate,
    # same fail-closed default as REMOTE_UI_TOKEN above.
    robot_credential_store = robot_credential_store or load_robot_tokens_from_env()
    robot_connection_manager = robot_connection_manager or RobotConnectionManager()
    # Phase 24c (ADR 0023): process-local like the connection manager.
    robot_voice_manager = robot_voice_manager or RobotVoiceManager(robot_connection_manager)
    app.state.robot_credential_store = robot_credential_store
    app.state.robot_connection_manager = robot_connection_manager
    app.state.robot_voice_manager = robot_voice_manager

    async def stop_voice_on_logout() -> None:
        await robot_voice_manager.stop_all("Owner logged out")

    default_chat_user_id = owner_user_id if accounts_service_token else telegram_default_user_id
    install_operator_routes(app, require_remote_auth, companion_core_client, get_client,
                            login_enabled=bool(session_secret_key), telegram_enabled=telegram_enabled,
                            default_user_id=default_chat_user_id,
                            owner_bound=bool(accounts_service_token), on_logout=stop_voice_on_logout)

    install_robot_ws_routes(
        app,
        robot_credential_store,
        robot_connection_manager,
        heartbeat_interval=robot_ws_heartbeat_interval,
        watchdog_timeout=robot_ws_watchdog_timeout,
        on_message=robot_voice_manager.on_robot_message,
        on_disconnect=robot_voice_manager.on_robot_disconnect,
    )
    app.state.webrtc_connections = set()
    if not owns_registry:
        app.state.registry = registry
    if not owns_session_store:
        app.state.session_store = session_store
    if not owns_telegram_chat_registry:
        app.state.telegram_chat_registry = telegram_chat_registry
    if not owns_audit_log:
        app.state.audit_log = audit_log
    if not owns_notification_queue:
        app.state.notification_queue = notification_queue

    async def get_robot_or_404(robot_id: str) -> Robot:
        robot = await app.state.registry.get(robot_id)
        if robot is None:
            raise HTTPException(status_code=404, detail=f"unknown robot '{robot_id}'")
        return robot

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(ROBOTS)
    async def register_robot(robot: Robot) -> Robot:
        await app.state.registry.register(robot)
        return robot

    @app.get(ROBOTS)
    async def list_robots() -> list[Robot]:
        return await app.state.registry.list()

    @app.get("/robots/{robot_id}/state", dependencies=[Depends(require_remote_auth)])
    async def robot_state(robot_id: str) -> dict:
        robot = await get_robot_or_404(robot_id)
        try:
            return await get_client(robot).get_state()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"robot '{robot_id}' unreachable: {exc}") from exc

    @app.get("/robots/{robot_id}/behaviours", dependencies=[Depends(require_remote_auth)])
    async def robot_behaviours(robot_id: str) -> dict:
        robot = await get_robot_or_404(robot_id)
        try:
            return await get_client(robot).list_behaviours()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"robot '{robot_id}' unreachable: {exc}") from exc

    @app.post("/robots/{robot_id}/behaviour/{name}", dependencies=[Depends(require_remote_auth)])
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

    @app.post(ROBOTS_STANDBY, dependencies=[Depends(require_remote_auth)])
    async def robots_standby() -> list[dict]:
        """Phase 22b: owner-requested remote "turn off/standby" command —
        parks and de-torques every registered robot, safe to physically
        handle afterwards. No {robot_id} in the path (unlike
        /robots/{robot_id}/behaviour above): this deployment is
        single-robot in practice, and looping the registry here — the
        same pattern trigger_gesture already uses — avoids needing
        callers (companion-core's deterministic intent) to track a robot
        id just to ask "turn everything off". Per-robot results, not a
        single pass/fail, since one robot's failure shouldn't hide
        another's success."""
        results = []
        for robot in await app.state.registry.list():
            try:
                status = await get_client(robot).daemon_standby()
                results.append({"robot_id": robot.robot_id, "ok": True, **status})
            except httpx.HTTPStatusError as exc:
                results.append(
                    {"robot_id": robot.robot_id, "ok": False, "error": f"{exc.response.status_code}: {exc.response.text}"}
                )
            except httpx.HTTPError as exc:
                results.append({"robot_id": robot.robot_id, "ok": False, "error": f"unreachable: {exc}"})
        return results

    @app.post(ROBOTS_RESUME, dependencies=[Depends(require_remote_auth)])
    async def robots_resume(wake_up: bool = True) -> list[dict]:
        """Resumes every registered robot previously put into standby.
        `wake_up=True` (default) replays the daemon's own wake-up motion —
        see AGENTS.md/docs/deployment.md for the owner-present exception
        this requires for a real daemon; this route itself doesn't gate
        that, `require_remote_auth` (the same owner-bound credential every
        channel already authenticates with) is the gate."""
        results = []
        for robot in await app.state.registry.list():
            try:
                status = await get_client(robot).daemon_resume(wake_up=wake_up)
                results.append({"robot_id": robot.robot_id, "ok": True, **status})
            except httpx.HTTPStatusError as exc:
                results.append(
                    {"robot_id": robot.robot_id, "ok": False, "error": f"{exc.response.status_code}: {exc.response.text}"}
                )
            except httpx.HTTPError as exc:
                results.append({"robot_id": robot.robot_id, "ok": False, "error": f"unreachable: {exc}"})
        return results

    @app.get("/sessions/{user_id}")
    async def get_session(user_id: str) -> AgentSession:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")
        return session

    @app.patch("/sessions/{user_id}/mode", dependencies=[Depends(require_remote_auth)])
    async def set_session_mode(user_id: str, request: SetModeRequest) -> AgentSession:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")
        return await app.state.session_store.set_mode(session, request.interaction_mode)

    @app.patch("/sessions/{user_id}/dnd", dependencies=[Depends(require_remote_auth)])
    async def set_session_dnd(user_id: str, request: SetDndRequest) -> AgentSession:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")
        session = await app.state.session_store.set_dnd(session, request.dnd)
        # Turning DND off is one of the two natural hooks this phase uses
        # instead of a background poller (docs/adr/0014) — deliver whatever
        # queued up while occupied, right now.
        if not request.dnd:
            await flush_notifications(user_id, session)
        return session

    @app.patch("/sessions/{user_id}/privacy-context", dependencies=[Depends(require_remote_auth)])
    async def set_session_privacy_context(user_id: str, request: SetPrivacyContextRequest) -> AgentSession:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")
        was_meeting = session.privacy_context == PrivacyContext.MEETING
        session = await app.state.session_store.set_privacy_context(session, request.privacy_context)
        if was_meeting and request.privacy_context != PrivacyContext.MEETING:
            await flush_notifications(user_id, session)
        return session

    @app.get("/audit/{user_id}")
    async def get_audit_log(user_id: str, limit: int = 50) -> list[AuditEntry]:
        return await app.state.audit_log.list_for_user(user_id, limit=limit)

    @app.get("/notifications/{user_id}")
    async def list_notifications(user_id: str) -> list[QueuedNotification]:
        return await app.state.notification_queue.list_for_user(user_id)

    @app.post("/notifications/{user_id}/flush")
    async def flush_notifications_endpoint(user_id: str) -> list[ReminderRoutingResult]:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")
        return await flush_notifications(user_id, session)

    async def push_to_telegram(user_id: str, text: str) -> bool:
        if telegram_client is None:
            return False
        chat_id = await app.state.telegram_chat_registry.get_chat_id(user_id)
        if accounts_service_token and (str(chat_id) != telegram_owner_chat or user_id != owner_user_id):
            return False
        if chat_id is None:
            return False
        delivered = False
        with contextlib.suppress(httpx.HTTPError):
            await telegram_client.send_message(chat_id, text)
            delivered = True
        return delivered

    async def robot_available() -> bool:
        """Best-effort "presence" check (docs/adr/0014): is there a robot
        registered and actually reachable to perform a gesture right now?
        A GESTURE action downgrades to TEXT when this is false rather than
        silently no-op'ing the robot half of "phone alert plus attention
        gesture"."""
        for robot in await app.state.registry.list():
            with contextlib.suppress(httpx.HTTPError):
                state = await get_client(robot).get_state()
                if state.get("embodiment_state") != "disconnected":
                    return True
        return False

    async def trigger_gesture(behaviour: Behaviour) -> None:
        for robot in await app.state.registry.list():
            with contextlib.suppress(httpx.HTTPError):
                await get_client(robot).trigger_behaviour(behaviour.value)

    async def flush_notifications(user_id: str, session: AgentSession) -> list[ReminderRoutingResult]:
        """Deliver everything queued for `user_id` right now. Shared by the
        explicit POST /notifications/{user_id}/flush and the two PATCH
        endpoints above whose whole point is "the user is no longer
        occupied" — not itself re-gated by interruption_policy, since the
        occupied condition that caused the queueing has, by construction,
        just ended."""
        queued = await app.state.notification_queue.clear_for_user(user_id)
        results: list[ReminderRoutingResult] = []
        for notification in queued:
            base_channel = resolve_delivery_channel(session.interaction_mode, session.active_channel)
            delivery_channel = apply_privacy_override(base_channel, notification.privacy, session.active_channel)

            await app.state.audit_log.record(
                user_id=user_id,
                session_id=session.session_id,
                channel=session.active_channel,
                mode=session.interaction_mode,
                privacy=notification.privacy,
                base_channel=base_channel,
                delivery_channel=delivery_channel,
                action=InterruptionAction.INTERRUPT,
            )

            delivered = False
            if delivery_channel == Channel.TELEGRAM:
                delivered = await push_to_telegram(user_id, notification.text)
            session = await app.state.session_store.record_interruption(session, datetime.now(UTC))

            results.append(
                ReminderRoutingResult(
                    event_id=notification.source_event_id or notification.id,
                    text=notification.text,
                    delivery_channel=delivery_channel,
                    action=InterruptionAction.INTERRUPT,
                    delivered=delivered,
                )
            )
        return results

    @app.post("/calendar/check-reminders/{user_id}")
    async def check_reminders(user_id: str, within_minutes: int = 15) -> list[ReminderRoutingResult]:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")

        now = datetime.now(UTC)
        try:
            reminders = await companion_core_client.due_reminders(within_minutes=within_minutes)
            current_events = await companion_core_client.events_in_progress(now)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"companion-core unreachable: {exc}") from exc

        occupied = is_occupied(
            dnd=session.dnd,
            privacy_context=session.privacy_context,
            event_in_progress=bool(current_events),
        )
        available = await robot_available()

        results: list[ReminderRoutingResult] = []
        for reminder in reminders:
            privacy = Privacy(reminder["privacy"])
            urgency = Urgency(reminder["urgency"])
            base_channel = resolve_delivery_channel(session.interaction_mode, session.active_channel)
            delivery_channel = apply_privacy_override(base_channel, privacy, session.active_channel)

            action = decide_action(
                occupied=occupied,
                urgency=urgency,
                last_interruption_at=session.last_interruption_at,
                now=now,
            )
            action = downgrade_for_presence(action, robot_available=available)

            await app.state.audit_log.record(
                user_id=user_id,
                session_id=session.session_id,
                channel=session.active_channel,
                mode=session.interaction_mode,
                privacy=privacy,
                base_channel=base_channel,
                delivery_channel=delivery_channel,
                action=action,
            )

            delivered = False
            if action is InterruptionAction.QUEUE:
                await app.state.notification_queue.enqueue(
                    user_id=user_id,
                    text=reminder["text"],
                    privacy=privacy,
                    urgency=urgency,
                    source_event_id=reminder["event_id"],
                )
            elif action is not InterruptionAction.IGNORE:
                if action is InterruptionAction.GESTURE:
                    # docs §4: "Urgent event -> phone alert plus Reachy
                    # attention gesture" — the gesture is additional to,
                    # not instead of, the push below.
                    await trigger_gesture(Behaviour.IMPORTANT_NOTICE)
                if delivery_channel == Channel.TELEGRAM:
                    delivered = await push_to_telegram(user_id, reminder["text"])
                if action is InterruptionAction.INTERRUPT:
                    session = await app.state.session_store.record_interruption(session, now)

            results.append(
                ReminderRoutingResult(
                    event_id=reminder["event_id"],
                    text=reminder["text"],
                    delivery_channel=delivery_channel,
                    action=action,
                    delivered=delivered,
                )
            )

        return results

    def _overall_urgency(items: list[dict]) -> Urgency:
        """Phase 18 (docs/adr/0015): a single proactive delivery needs one
        urgency to feed decide_action — the highest urgency among the
        briefing's items, so one imminent meeting is enough to earn the
        whole briefing a GESTURE while occupied. LOW (not NORMAL) when
        there's nothing to report at all, so an empty briefing never
        out-prioritizes a real notification competing for the same
        cooldown."""
        urgencies = {Urgency(item["urgency"]) for item in items}
        if Urgency.URGENT in urgencies:
            return Urgency.URGENT
        if Urgency.NORMAL in urgencies:
            return Urgency.NORMAL
        return Urgency.LOW

    def _format_briefing_text(items: list[dict]) -> str:
        if not items:
            return "Nothing on your briefing right now."
        return "Daily briefing:\n" + "\n".join(f"- {item['text']}" for item in items)

    @app.post("/briefing/{user_id}")
    async def deliver_briefing(user_id: str) -> BriefingDeliveryResult:
        """Phase 18 (docs/adr/0015): "Reachy greets; detailed briefing is
        privately delivered." The greeting gesture is unconditional (a wave
        costs nothing and isn't itself private information) — the detailed
        content is what goes through the exact same occupied-aware routing
        check_reminders (Phase 17) uses, reusing decide_action/
        ReminderRoutingResult-shaped flow per ADR 0014's own forward note."""
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no session for user '{user_id}'")

        now = datetime.now(UTC)
        try:
            items = await companion_core_client.get_briefing()
            current_events = await companion_core_client.events_in_progress(now)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"companion-core unreachable: {exc}") from exc

        available = await robot_available()
        greeted = False
        if available:
            await trigger_gesture(Behaviour.GREETING)
            greeted = True

        occupied = is_occupied(
            dnd=session.dnd,
            privacy_context=session.privacy_context,
            event_in_progress=bool(current_events),
        )
        urgency = _overall_urgency(items)
        action = decide_action(
            occupied=occupied,
            urgency=urgency,
            last_interruption_at=session.last_interruption_at,
            now=now,
        )
        action = downgrade_for_presence(action, robot_available=available)

        text = _format_briefing_text(items)
        base_channel = resolve_delivery_channel(session.interaction_mode, session.active_channel)
        # "...privately delivered": forced WORK_PRIVATE, the same mechanism
        # check_reminders uses to keep aggregated work data off Reachy's
        # speaker regardless of mode — a briefing is inherently a work-data
        # aggregate, not classified per-item privacy at delivery time.
        delivery_channel = apply_privacy_override(base_channel, Privacy.WORK_PRIVATE, session.active_channel)

        await app.state.audit_log.record(
            user_id=user_id,
            session_id=session.session_id,
            channel=session.active_channel,
            mode=session.interaction_mode,
            privacy=Privacy.WORK_PRIVATE,
            base_channel=base_channel,
            delivery_channel=delivery_channel,
            action=action,
        )

        delivered = False
        if action is InterruptionAction.QUEUE:
            await app.state.notification_queue.enqueue(
                user_id=user_id,
                text=text,
                privacy=Privacy.WORK_PRIVATE,
                urgency=urgency,
                source_event_id=None,
            )
        elif action is not InterruptionAction.IGNORE:
            if action is InterruptionAction.GESTURE:
                await trigger_gesture(Behaviour.IMPORTANT_NOTICE)
            if delivery_channel == Channel.TELEGRAM:
                delivered = await push_to_telegram(user_id, text)
            if action is InterruptionAction.INTERRUPT:
                session = await app.state.session_store.record_interruption(session, now)

        return BriefingDeliveryResult(
            greeted=greeted,
            items=[BriefingItemResult(**item) for item in items],
            text=text,
            delivery_channel=delivery_channel,
            action=action,
            delivered=delivered,
        )

    async def handle_inbound_message(message: InboundMessage) -> MessageResponse:
        """Shared by POST /messages and the Telegram poll loop — the same
        normalization path regardless of which channel a message arrived
        on, per ADR 0002."""
        session = await app.state.session_store.get_or_create(message.user_id, message.channel)
        if session.active_channel != message.channel:
            session = await app.state.session_store.touch_channel(session, message.channel)

        try:
            result = await companion_core_client.send_turn(
                session.session_id,
                session.conversation_id,
                message.channel.value,
                message.text,
                input_modality=message.input_modality.value,
                force_frontier=message.force_frontier,
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

    # Caller-upload diagnostic, not the robot workflow (robot_voice.py).
    # Owner auth and the OWNER_USER_ID binding come from private_work_routes
    # above, which runs before this handler (so before any STT); a hub with
    # production stores cannot start without the ACCOUNTS_SERVICE_TOKEN that
    # enables it. Only injected-store dev/test apps leave it open, like /messages.
    @app.post("/voice/turn")
    async def voice_turn(user_id: str = Form(...), audio: UploadFile = File(...)) -> Response:  # noqa: B008
        wav_bytes = await audio.read()

        # faster-whisper and the espeak-ng subprocess are both blocking/
        # CPU-bound; running them inline would stall the event loop for
        # every other request while a transcription/synthesis is in flight.
        transcript = await asyncio.to_thread(transcribe, wav_bytes)
        if not transcript:
            raise HTTPException(status_code=422, detail="no speech detected in audio")

        response = await handle_inbound_message(
            InboundMessage(
                user_id=user_id, channel=Channel.REACHY, text=transcript, input_modality=InputModality.VOICE
            )
        )
        reply_wav = await asyncio.to_thread(synthesize, response.reply)

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

    def resolve_voice_user(requested: str | None) -> str:
        user_id = requested or default_chat_user_id
        # Same owner binding private_work_routes applies to /messages.
        if accounts_service_token and user_id != owner_user_id:
            raise HTTPException(403, "This account belongs to the signed-in owner")
        return user_id

    async def voice_transcribe(wav_bytes: bytes) -> str:
        return await asyncio.to_thread(transcribe, wav_bytes)

    async def voice_synthesize(text: str) -> bytes:
        return await asyncio.to_thread(synthesize, text)

    async def voice_converse(user_id: str, transcript: str) -> ConversationReply:
        response = await handle_inbound_message(
            InboundMessage(user_id=user_id, channel=Channel.REACHY, text=transcript, input_modality=InputModality.VOICE)
        )
        return ConversationReply(reply=response.reply, delivery_channel=response.delivery_channel)

    async def voice_session_flags(user_id: str) -> tuple[bool, PrivacyContext]:
        session = await app.state.session_store.get_by_user(user_id)
        if session is None:
            return False, PrivacyContext.UNKNOWN
        return session.dnd, session.privacy_context

    async def voice_deliver_private(user_id: str, channel: Channel, text: str) -> bool:
        return channel == Channel.TELEGRAM and await push_to_telegram(user_id, text)

    async def registered_robot_ids() -> list[str]:
        return [robot.robot_id for robot in await app.state.registry.list()]

    install_robot_voice_routes(
        app,
        robot_voice_manager,
        robot_credential_store,
        require_remote_auth,
        resolve_voice_user,
        VoiceTurnPipeline(
            transcribe=voice_transcribe,
            converse=voice_converse,
            session_flags=voice_session_flags,
            synthesize=voice_synthesize,
            deliver_private=voice_deliver_private,
            speech_withheld_reason=robot_speech_withheld_reason,
        ),
        registered_robot_ids,
    )

    @app.post("/webrtc/offer")
    async def webrtc_offer(request: WebRTCOfferRequest) -> WebRTCAnswerResponse:
        robot = await get_robot_or_404(request.robot_id)
        client = get_client(robot)

        async def trigger_behaviour(behaviour: Behaviour) -> None:
            # A failed behaviour trigger (robot briefly unreachable) must
            # not break the call — same graceful-degradation as the
            # heartbeat loop above, not a reason to drop the audio turn.
            with contextlib.suppress(httpx.HTTPError):
                await client.trigger_behaviour(behaviour.value)

        async def ask_agent(transcript: str) -> str:
            response = await handle_inbound_message(
                InboundMessage(
                    user_id=request.user_id,
                    channel=Channel.WEB,
                    text=transcript,
                    input_modality=InputModality.VOICE,
                )
            )
            return response.reply

        turn_handler = CallTurnHandler(
            transcribe=transcribe,
            synthesize=synthesize,
            trigger_behaviour=trigger_behaviour,
            ask_agent=ask_agent,
        )
        answer_sdp, answer_type, pc = await negotiate_call(
            offer_sdp=request.sdp, offer_type=request.type, turn_handler=turn_handler
        )
        app.state.webrtc_connections.add(pc)

        @pc.on("connectionstatechange")
        async def on_connection_state_change() -> None:
            if pc.connectionState in ("failed", "closed"):
                app.state.webrtc_connections.discard(pc)
                await pc.close()

        return WebRTCAnswerResponse(sdp=answer_sdp, type=answer_type)

    @app.post("/robots/{robot_id}/speak", dependencies=[Depends(require_remote_auth)])
    async def speak_through_robot(robot_id: str, request: SpeakRequest) -> dict:
        """Phase 16/ADR 0013: synthesizes text and plays it through the
        robot directly — no companion_core_client call anywhere in this
        path, unlike /messages, /voice/turn, and /webrtc/offer, which all
        route through handle_inbound_message. This is what actually
        satisfies "control basic Reachy functions without Companion
        Core," not just the auth gate above."""
        robot = await get_robot_or_404(robot_id)
        client = get_client(robot)
        wav_bytes = await asyncio.to_thread(synthesize, request.text)
        try:
            return await client.play_audio(wav_bytes)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"robot '{robot_id}' unreachable: {exc}") from exc

    @app.post("/webrtc/telepresence/offer", dependencies=[Depends(require_remote_auth)])
    async def webrtc_telepresence_offer(request: TelepresenceOfferRequest) -> WebRTCAnswerResponse:
        robot = await get_robot_or_404(request.robot_id)
        client = get_client(robot)

        with contextlib.suppress(httpx.HTTPError):
            await client.set_remote(True)

        async def frame_source() -> bytes:
            return await client.get_camera_frame()

        answer_sdp, answer_type, pc = await negotiate_telepresence(
            offer_sdp=request.sdp, offer_type=request.type, frame_source=frame_source
        )
        app.state.webrtc_connections.add(pc)

        @pc.on("connectionstatechange")
        async def on_connection_state_change() -> None:
            if pc.connectionState in ("failed", "closed"):
                app.state.webrtc_connections.discard(pc)
                await pc.close()
                with contextlib.suppress(httpx.HTTPError):
                    await client.set_remote(False)

        return WebRTCAnswerResponse(sdp=answer_sdp, type=answer_type)

    # clients/web-pwa/ — the "Call Reachy" UI itself. Served by reachy-hub
    # (ADR 0001: reachy-hub owns web UI), reachable through Caddy at
    # /hub/app/ (Caddy's handle_path strips the /hub prefix before
    # forwarding). html=True serves index.html for the directory root.
    web_pwa_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "clients", "web-pwa")
    if os.path.isdir(web_pwa_dir):
        app.mount("/app", StaticFiles(directory=web_pwa_dir, html=True), name="web-pwa")

    @app.get("/ui", include_in_schema=False)
    async def operator_ui_redirect():
        # Relative location survives Caddy's stripped /hub prefix.
        return RedirectResponse("ui/")

    operator_ui_dir = os.path.join(os.path.dirname(web_pwa_dir), "operator-ui")
    if os.path.isdir(operator_ui_dir):
        app.mount("/ui", StaticFiles(directory=operator_ui_dir, html=True), name="operator-ui")

    return app
