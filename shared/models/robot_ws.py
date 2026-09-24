"""Message schemas for the ADR 0019 robot<->hub WSS control connection.

Phase 22's first slice implements only the connectivity substrate:
authentication (at the transport layer, before any of these messages are
parsed — see robot_ws.py in reachy-hub), protocol negotiation,
registration, generation fencing, and heartbeat/ack liveness. Phase 24c
adds conversation control only (voice_start/voice_stop/voice_state, ADR
0023), gated by the robot's advertised capability rather than a protocol
version bump. General semantic command/result/cancellation schemas are
still a follow-up; behaviour, camera and speak commands use HTTP.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from shared.models.robot_voice import RobotVoiceState, VoiceLimits


class WSMessageType(StrEnum):
    REGISTER = "register"
    REGISTERED = "registered"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    ERROR = "error"
    # Phase 24c (ADR 0023): conversation control only, never audio.
    VOICE_START = "voice_start"
    VOICE_STOP = "voice_stop"
    VOICE_STATE = "voice_state"


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


class VoiceStartMessage(BaseModel):
    """Hub -> robot: begin listening for `voice_session_id`. Sent only after
    an owner-authenticated start (ADR 0023); a robot never self-starts."""

    type: Literal[WSMessageType.VOICE_START] = WSMessageType.VOICE_START
    voice_session_id: str
    limits: VoiceLimits = VoiceLimits()


class VoiceStopMessage(BaseModel):
    """Hub -> robot: stop capture, discard pending work and stop playback."""

    type: Literal[WSMessageType.VOICE_STOP] = WSMessageType.VOICE_STOP
    voice_session_id: str
    reason: str


class VoiceStateMessage(BaseModel):
    """Robot -> hub: the robot's own half of the turn state. `detail` is a
    sanitized error summary, never a transcript."""

    type: Literal[WSMessageType.VOICE_STATE] = WSMessageType.VOICE_STATE
    voice_session_id: str
    state: RobotVoiceState
    detail: str | None = None


# WS close codes in the 4000-4999 application-defined range (RFC 6455 s7.4.2).
CLOSE_AUTH_FAILED = 4401
CLOSE_VERSION_MISMATCH = 4400
CLOSE_REGISTRATION_INVALID = 4422
CLOSE_FENCED_BY_NEWER_CONNECTION = 4409
CLOSE_WATCHDOG_TIMEOUT = 4408
