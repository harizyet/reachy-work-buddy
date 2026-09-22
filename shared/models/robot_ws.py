"""Message schemas for the ADR 0019 robot<->hub WSS control connection.

Phase 22's first slice implements only the connectivity substrate:
authentication (at the transport layer, before any of these messages are
parsed — see robot_ws.py in reachy-hub), protocol negotiation,
registration, generation fencing, and heartbeat/ack liveness. ADR 0019
also calls for "semantic commands, accepted/completed results,
cancellation" schemas; those are a deliberate follow-up once this
connectivity layer has been verified against a live daemon/robot, not
part of this set. Don't assume command routing works over this
connection yet — see docs/verification/phase-22-inventory-2026-09-22.md
and HANDOVER.md for the current status.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class WSMessageType(StrEnum):
    REGISTER = "register"
    REGISTERED = "registered"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    ERROR = "error"


class RegisterMessage(BaseModel):
    """First message a robot sends once the WS handshake completes.

    `robot_id` here must match the identity already bound to the
    authenticating credential, checked before this message is even
    parsed — ADR 0019: "claims in a registration message cannot select
    another identity."
    """

    type: Literal[WSMessageType.REGISTER] = WSMessageType.REGISTER
    robot_id: str
    protocol_version: int
    capabilities: list[str] = []
    sim: bool = False


class RegisteredMessage(BaseModel):
    """Hub's registration acknowledgement. `generation` fences this
    connection: a later authenticated connection for the same robot_id
    gets a higher generation, and the hub closes this one."""

    type: Literal[WSMessageType.REGISTERED] = WSMessageType.REGISTERED
    robot_id: str
    generation: int


class HeartbeatMessage(BaseModel):
    type: Literal[WSMessageType.HEARTBEAT] = WSMessageType.HEARTBEAT


class HeartbeatAckMessage(BaseModel):
    type: Literal[WSMessageType.HEARTBEAT_ACK] = WSMessageType.HEARTBEAT_ACK


class ErrorMessage(BaseModel):
    """Sanitized only — never include credential values or raw exception
    internals (ADR 0019: "sanitized errors")."""

    type: Literal[WSMessageType.ERROR] = WSMessageType.ERROR
    code: str
    detail: str


# WS close codes in the 4000-4999 application-defined range (RFC 6455 s7.4.2).
CLOSE_AUTH_FAILED = 4401
CLOSE_VERSION_MISMATCH = 4400
CLOSE_REGISTRATION_INVALID = 4422
CLOSE_FENCED_BY_NEWER_CONNECTION = 4409
CLOSE_WATCHDOG_TIMEOUT = 4408
