"""Outbound WSS control connection to reachy-hub, per ADR 0019.

First slice: connects, authenticates, registers, responds to hub
heartbeats, and reconnects with exponential backoff on any failure or
disconnect. Semantic command handling (receiving and executing
behaviour/camera/audio commands over this connection) is a deliberate
follow-up — see shared/models/robot_ws.py's docstring for the same scope
boundary. HTTP remains the dev/simulation transport per ADR 0019; this
client is additive to reachy-embodiment's existing local HTTP server, not
a replacement for it — the HTTP API keeps serving local/dev callers
regardless of this connection's state.

Not yet verified against a live reachy-hub over a real network — see
HANDOVER.md's Phase 22 status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random

import websockets
from websockets.exceptions import WebSocketException

from shared.models.robot_ws import (
    ErrorMessage,
    HeartbeatAckMessage,
    RegisteredMessage,
    RegisterMessage,
    WSMessageType,
)
from shared.protocols.robot_ws import PROTOCOL_VERSION, ROBOTS_CONNECT

log = logging.getLogger(__name__)

MIN_BACKOFF = 1.0
MAX_BACKOFF = 30.0


def next_backoff(current: float, *, min_backoff: float = MIN_BACKOFF, max_backoff: float = MAX_BACKOFF) -> float:
    """Pure doubling-with-cap sequence, exposed standalone so the
    reconnect cadence is testable without real sleeps. ADR 0019: "1, 2,
    4, 8 seconds, capped at 30 seconds"."""
    return min(current * 2, max_backoff)


def _as_ws_url(url: str) -> str:
    """Derives ws:// or wss:// from an http(s):// hub URL, per ADR 0019
    ("the robot knows the hub's configured HTTPS/WSS destination") and
    deploy/reachy/.env.example's documented HUB_WS_URL contract. A URL
    already given as ws(s):// passes through unchanged.
    """
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url


class RobotWSClient:
    """Maintains one outbound WS connection to `hub_ws_url`, reconnecting
    forever until its `run()` task is cancelled. Intended usage:
    `task = asyncio.create_task(client.run())` in a service's lifespan,
    `task.cancel()` (then await it) on shutdown.
    """

    def __init__(
        self,
        hub_ws_url: str,
        robot_id: str,
        token: str,
        *,
        capabilities: list[str] | None = None,
        sim: bool = False,
        registration_timeout: float = 5.0,
    ) -> None:
        self._hub_ws_url = _as_ws_url(hub_ws_url.rstrip("/")) + ROBOTS_CONNECT
        self._robot_id = robot_id
        self._token = token
        self._capabilities = list(capabilities or [])
        self._sim = sim
        self._registration_timeout = registration_timeout

        self.generation: int | None = None
        self.connected = False

    async def run(self) -> None:
        """Runs until cancelled: connect, register, respond to
        heartbeats, and on any failure or disconnect, wait with
        exponential backoff+jitter and try again. Never returns on its
        own short of cancellation — a permanently-unreachable hub just
        means permanent reconnect attempts, matching ADR 0019: "Presence
        starts without the hub and never waits on reconnect" (this task
        runs alongside, not gating, the rest of the service).
        """
        backoff = MIN_BACKOFF
        while True:
            try:
                await self._connect_once()
                backoff = MIN_BACKOFF  # reset after a session that got as far as registering
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any failure here must trigger reconnect, not crash the task
                log.warning("robot WS connection to hub failed: %s", exc)
            finally:
                self.connected = False
                self.generation = None

            jitter = backoff * random.uniform(0.8, 1.2)
            await asyncio.sleep(jitter)
            backoff = next_backoff(backoff)

    async def _connect_once(self) -> None:
        headers = {"X-Robot-Id": self._robot_id, "Authorization": f"Bearer {self._token}"}
        async with websockets.connect(self._hub_ws_url, additional_headers=headers) as ws:
            await ws.send(
                RegisterMessage(
                    robot_id=self._robot_id,
                    protocol_version=PROTOCOL_VERSION,
                    capabilities=self._capabilities,
                    sim=self._sim,
                ).model_dump_json()
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=self._registration_timeout)
            message = json.loads(raw)

            if message.get("type") == WSMessageType.ERROR:
                err = ErrorMessage.model_validate(message)
                raise WebSocketException(f"hub rejected registration: {err.code}: {err.detail}")

            registered = RegisteredMessage.model_validate(message)
            self.generation = registered.generation
            self.connected = True
            log.info("registered with hub as %s, generation %s", self._robot_id, self.generation)

            async for raw_message in ws:
                message = json.loads(raw_message)
                message_type = message.get("type")
                if message_type == WSMessageType.HEARTBEAT:
                    await ws.send(HeartbeatAckMessage().model_dump_json())
                elif message_type == WSMessageType.ERROR:
                    err = ErrorMessage.model_validate(message)
                    log.warning("hub reported error: %s: %s", err.code, err.detail)
                    return  # triggers a reconnect via run()'s loop
                else:
                    log.debug("ignoring message type %r (no command routing yet)", message_type)
