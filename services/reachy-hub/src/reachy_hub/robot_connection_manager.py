"""Tracks live, process-local WSS robot connections for ADR 0019.

Deliberately separate from robot_registry.py's `Robot` (provisioned
identity/base_url metadata — ADR 0019's HTTP dev/simulation transport
still uses that). ADR 0019: "Keep provisioned identity/credential
metadata separate from live state... Active sockets and pending
requests are process-local and never restored as online after hub
restart." This manager only ever exists in-memory; nothing here is
persisted, and it starts empty on every hub process start.

Phase 22's first slice covers connectivity only: registration and
generation fencing. There is no pending-request/command tracking here
yet — that's a follow-up once semantic command routing over this
connection is built (see shared/models/robot_ws.py's docstring).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

log = logging.getLogger(__name__)


class SendableConnection(Protocol):
    """Minimal surface this manager needs from a live socket — lets
    tests use a fake instead of a real Starlette WebSocket. A real
    `starlette.websockets.WebSocket` already satisfies this exactly."""

    async def close(self, code: int = 1000) -> None: ...


@dataclass
class RobotConnection:
    robot_id: str
    generation: int
    socket: SendableConnection
    capabilities: list[str]
    sim: bool
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat_ack_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class RobotConnectionManager:
    """One authoritative connection per robot_id. Registering a new
    connection for an already-connected robot_id atomically fences out
    (and closes) the previous one — ADR 0019: "An authenticated new
    connection atomically replaces and fences the previous generation."

    Phase 22 uses one hub worker (ADR 0019); this manager's state is
    process-local in-memory dicts, which is only correct under that
    assumption. Multiple hub workers need an explicit shared
    connection-routing design first, not this class as-is.
    """

    def __init__(self) -> None:
        self._connections: dict[str, RobotConnection] = {}
        self._generation_counters: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, robot_id: str, socket: SendableConnection, *, capabilities: list[str], sim: bool
    ) -> RobotConnection:
        async with self._lock:
            generation = self._generation_counters.get(robot_id, 0) + 1
            self._generation_counters[robot_id] = generation
            previous = self._connections.get(robot_id)
            connection = RobotConnection(
                robot_id=robot_id,
                generation=generation,
                socket=socket,
                capabilities=list(capabilities),
                sim=sim,
            )
            self._connections[robot_id] = connection

        if previous is not None:
            log.info(
                "robot %s: connection generation %s superseded by %s",
                robot_id,
                previous.generation,
                generation,
            )
            try:
                await previous.socket.close(code=4409)
            except Exception:
                log.warning("robot %s: closing superseded connection raised", robot_id, exc_info=True)

        return connection

    async def unregister(self, robot_id: str, generation: int) -> None:
        """No-ops if `generation` is no longer the current one — an old,
        already-fenced connection's own disconnect handler must not
        remove a newer connection that has since taken its place."""
        async with self._lock:
            current = self._connections.get(robot_id)
            if current is not None and current.generation == generation:
                del self._connections[robot_id]

    def get(self, robot_id: str) -> RobotConnection | None:
        return self._connections.get(robot_id)

    def is_online(self, robot_id: str) -> bool:
        return robot_id in self._connections

    def list_online(self) -> list[RobotConnection]:
        return list(self._connections.values())

    def record_liveness(self, robot_id: str, generation: int) -> None:
        """Called whenever any message is received on a connection —
        proof of life, not only on explicit heartbeat_ack (see robot_ws.py's
        connection loop for why: simpler and just as robust for this
        slice's watchdog purpose than a strict ping/ack-only rule)."""
        current = self._connections.get(robot_id)
        if current is not None and current.generation == generation:
            current.last_heartbeat_ack_at = datetime.now(UTC)
