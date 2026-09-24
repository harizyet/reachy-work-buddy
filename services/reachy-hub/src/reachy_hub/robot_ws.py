"""Hub-side WSS endpoint for ADR 0019's robot-initiated control connection.

Phase 22's first slice: authentication, protocol negotiation,
registration, generation fencing, and heartbeat-driven liveness/watchdog.
Phase 24c adds only conversation control (`on_message`/`on_disconnect`
feed robot_voice.py, ADR 0023). Behaviour/camera/audio commands still use
the HTTP EmbodimentClient path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from reachy_hub.robot_connection_manager import RobotConnection, RobotConnectionManager
from reachy_hub.robot_credential_store import RobotCredentialStore
from shared.models.robot_ws import (
    CLOSE_AUTH_FAILED,
    CLOSE_REGISTRATION_INVALID,
    CLOSE_VERSION_MISMATCH,
    CLOSE_WATCHDOG_TIMEOUT,
    ErrorMessage,
    HeartbeatMessage,
    RegisteredMessage,
    RegisterMessage,
    WSMessageType,
)
from shared.protocols.robot_ws import PROTOCOL_VERSION, ROBOTS_CONNECT

log = logging.getLogger(__name__)


async def connection_loop(
    websocket: WebSocket,
    manager: RobotConnectionManager,
    connection: RobotConnection,
    *,
    heartbeat_interval: float,
    watchdog_timeout: float,
    on_message: Callable[[RobotConnection, dict], Awaitable[None]] | None = None,
    on_disconnect: Callable[[RobotConnection], Awaitable[None]] | None = None,
) -> None:
    """One live connection's message loop: sends periodic heartbeats,
    treats any received message as liveness proof, and closes the
    connection if nothing is heard within `watchdog_timeout`. Exposed as
    a standalone function (not inlined in the route handler) so it's
    unit-testable against a fake socket without a real WS handshake —
    same rationale as presence.py's `tick()`.

    Cadence: 2 s heartbeat / 15 s watchdog (ADR 0019 addendum, Phase 24d).
    """
    last_seen = time.monotonic()
    try:
        while True:
            remaining = watchdog_timeout - (time.monotonic() - last_seen)
            if remaining <= 0:
                log.warning("robot %s: heartbeat watchdog expired, closing connection", connection.robot_id)
                await websocket.close(code=CLOSE_WATCHDOG_TIMEOUT)
                return

            try:
                raw = await asyncio.wait_for(websocket.receive_json(), timeout=min(heartbeat_interval, remaining))
            except TimeoutError:
                async with connection.send_lock:
                    await websocket.send_json(HeartbeatMessage().model_dump())
                continue

            # Any well-formed message counts as liveness, not only an
            # explicit heartbeat_ack — simpler than a strict ping/ack-only
            # rule and just as sufficient for this slice's watchdog purpose.
            last_seen = time.monotonic()
            manager.record_liveness(connection.robot_id, connection.generation)

            message_type = raw.get("type") if isinstance(raw, dict) else None
            if message_type in (WSMessageType.HEARTBEAT_ACK, WSMessageType.HEARTBEAT):
                continue
            if on_message is not None and isinstance(raw, dict):
                await on_message(connection, raw)
            else:
                log.debug("robot %s: ignoring message type %r", connection.robot_id, message_type)
    except WebSocketDisconnect:
        log.info("robot %s: WS disconnected (generation %s)", connection.robot_id, connection.generation)
    finally:
        await manager.unregister(connection.robot_id, connection.generation)
        if on_disconnect is not None:
            await on_disconnect(connection)


def install_robot_ws_routes(
    app: FastAPI,
    credential_store: RobotCredentialStore,
    connection_manager: RobotConnectionManager,
    *,
    heartbeat_interval: float = 2.0,
    # ADR 0019 started at 5 s pending real-jitter validation. On nano-1's
    # tailnet path (Phase 24d) a Tailscale path re-validation stalled the
    # robot's acks past 5 s while the link otherwise stayed up, dropping a
    # live voice session; 15 s rides out a few TCP retransmit backoffs.
    watchdog_timeout: float = 15.0,
    registration_timeout: float = 5.0,
    on_message: Callable[[RobotConnection, dict], Awaitable[None]] | None = None,
    on_disconnect: Callable[[RobotConnection], Awaitable[None]] | None = None,
) -> None:
    @app.websocket(ROBOTS_CONNECT)
    async def robots_connect(websocket: WebSocket) -> None:
        robot_id = websocket.headers.get("x-robot-id")
        authorization = websocket.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else None

        if not robot_id or not token or not await credential_store.verify(robot_id, token):
            # Closed without ever accepting — ADR 0019: never let an
            # unauthenticated control connection reach a data plane.
            # Credentials are read from headers only, never logged.
            await websocket.close(code=CLOSE_AUTH_FAILED)
            return

        await websocket.accept()

        try:
            raw = await asyncio.wait_for(websocket.receive_json(), timeout=registration_timeout)
        except (TimeoutError, WebSocketDisconnect):
            return

        try:
            register = RegisterMessage.model_validate(raw)
        except ValidationError:
            await websocket.send_json(
                ErrorMessage(code="invalid_registration", detail="malformed register message").model_dump()
            )
            await websocket.close(code=CLOSE_REGISTRATION_INVALID)
            return

        if register.robot_id != robot_id:
            # ADR 0019: "claims in a registration message cannot select
            # another identity" — the authenticated header identity wins.
            await websocket.send_json(
                ErrorMessage(
                    code="identity_mismatch",
                    detail="registration robot_id does not match authenticated identity",
                ).model_dump()
            )
            await websocket.close(code=CLOSE_REGISTRATION_INVALID)
            return

        if register.protocol_version != PROTOCOL_VERSION:
            await websocket.send_json(
                ErrorMessage(
                    code="version_mismatch", detail=f"server supports protocol version {PROTOCOL_VERSION}"
                ).model_dump()
            )
            await websocket.close(code=CLOSE_VERSION_MISMATCH)
            return

        connection = await connection_manager.register(
            robot_id, websocket, capabilities=register.capabilities, sim=register.sim
        )
        await websocket.send_json(RegisteredMessage(robot_id=robot_id, generation=connection.generation).model_dump())

        await connection_loop(
            websocket,
            connection_manager,
            connection,
            heartbeat_interval=heartbeat_interval,
            watchdog_timeout=watchdog_timeout,
            on_message=on_message,
            on_disconnect=on_disconnect,
        )
