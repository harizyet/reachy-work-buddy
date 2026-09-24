"""Robot microphone/speaker conversation sessions (Phase 24c, ADR 0023).

The hub owns each session: the owner starts it from an authenticated
control, then keeps it alive by renewing a short lease; logout, lease
lapse, maximum duration, idle timeout, robot disconnect and explicit stop
all end it. The robot captures only while it holds a session the hub sent
it over the ADR 0019 control socket, and uploads each bounded utterance to
`ROBOT_VOICE_TURN` with its own credential. Audio never travels over the
control socket.

State here is process-local, like `RobotConnectionManager`: a hub restart
drops every session and the robot, losing its socket, stops capturing and
does not resume on reconnect.

`expire()` takes no time argument; the injected `clock` makes lease and
deadline checks testable without sleeping.
"""

from __future__ import annotations

import asyncio
import io
import logging
import secrets
import time
import wave
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response

from reachy_hub.robot_connection_manager import RobotConnection, RobotConnectionManager
from reachy_hub.robot_credential_store import RobotCredentialStore
from shared.models.robot_voice import (
    MAX_UTTERANCE_BYTES,
    ROBOT_GENERATION_HEADER,
    SAMPLE_RATE,
    VOICE_CAPABILITY,
    VOICE_OUTCOME_HEADER,
    VOICE_SESSION_HEADER,
    VOICE_TURN_HEADER,
    RobotVoiceAvailability,
    RobotVoiceState,
    StartVoiceRequest,
    VoiceLimits,
    VoiceOverview,
    VoiceSessionRef,
    VoiceSessionState,
    VoiceSessionStatus,
    VoiceTurnOutcome,
    VoiceTurnRecord,
)
from shared.models.robot_ws import (
    VoiceStartMessage,
    VoiceStateMessage,
    VoiceStopMessage,
    WSMessageType,
)
from shared.models.session import Channel, PrivacyContext
from shared.protocols.operator_api import (
    ROBOT_VOICE,
    ROBOT_VOICE_RENEW,
    ROBOT_VOICE_START,
    ROBOT_VOICE_STOP,
)
from shared.protocols.robot_ws import ROBOT_VOICE_TURN

log = logging.getLogger(__name__)

LEASE_SECONDS = 15.0
IDLE_TIMEOUT_SECONDS = 120.0
MAX_TURN_RECORDS = 20


class VoiceSessionError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class VoiceSession:
    voice_session_id: str
    robot_id: str
    user_id: str
    generation: int
    limits: VoiceLimits
    lease_expires_at: float
    deadline: float
    last_activity: float
    state: VoiceSessionState = VoiceSessionState.STARTING
    stop_reason: str | None = None
    last_error: str | None = None
    next_turn: int = 1
    in_flight_turn: int | None = None
    turns: deque[VoiceTurnRecord] = field(default_factory=lambda: deque(maxlen=MAX_TURN_RECORDS))

    @property
    def active(self) -> bool:
        return self.state != VoiceSessionState.STOPPED


class RobotVoiceManager:
    def __init__(
        self,
        connections: RobotConnectionManager,
        *,
        lease_seconds: float = LEASE_SECONDS,
        idle_timeout_seconds: float = IDLE_TIMEOUT_SECONDS,
        limits: VoiceLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._connections = connections
        self._lease_seconds = lease_seconds
        self._idle_timeout_seconds = idle_timeout_seconds
        self._limits = limits or VoiceLimits()
        self._clock = clock
        # One record per robot: the active session, or the most recently
        # stopped one so the owner can still read why it ended.
        self._sessions: dict[str, VoiceSession] = {}

    def status(self, session: VoiceSession) -> VoiceSessionStatus:
        now = self._clock()
        return VoiceSessionStatus(
            voice_session_id=session.voice_session_id,
            robot_id=session.robot_id,
            user_id=session.user_id,
            state=session.state,
            stop_reason=session.stop_reason,
            last_error=session.last_error,
            next_turn=session.next_turn,
            lease_seconds_remaining=max(0.0, session.lease_expires_at - now) if session.active else 0.0,
            session_seconds_remaining=max(0.0, session.deadline - now) if session.active else 0.0,
            turns=list(session.turns),
        )

    def overview(self, registered_robot_ids: list[str]) -> VoiceOverview:
        online = {conn.robot_id: conn for conn in self._connections.list_online()}
        robots = [
            RobotVoiceAvailability(
                robot_id=robot_id,
                online=robot_id in online,
                voice_capable=robot_id in online and VOICE_CAPABILITY in online[robot_id].capabilities,
            )
            for robot_id in sorted(set(registered_robot_ids) | set(online))
        ]
        sessions = sorted(self._sessions.values(), key=lambda s: (s.active, s.deadline), reverse=True)
        return VoiceOverview(robots=robots, session=self.status(sessions[0]) if sessions else None)

    def get(self, voice_session_id: str) -> VoiceSession:
        for session in self._sessions.values():
            if session.voice_session_id == voice_session_id:
                return session
        raise VoiceSessionError(404, "Unknown voice session")

    async def start(self, robot_id: str, user_id: str) -> VoiceSession:
        connection = self._connections.get(robot_id)
        if connection is None:
            raise VoiceSessionError(409, "Robot is not connected to the hub")
        if VOICE_CAPABILITY not in connection.capabilities:
            raise VoiceSessionError(409, "Voice conversation is not enabled on this robot")
        existing = self._sessions.get(robot_id)
        if existing is not None and existing.active:
            if existing.user_id != user_id:
                raise VoiceSessionError(409, "Robot is already in a voice session")
            return self.renew(existing.voice_session_id)

        now = self._clock()
        session = VoiceSession(
            voice_session_id=secrets.token_urlsafe(16),
            robot_id=robot_id,
            user_id=user_id,
            generation=connection.generation,
            limits=self._limits,
            lease_expires_at=now + self._lease_seconds,
            deadline=now + self._limits.max_session_seconds,
            last_activity=now,
        )
        self._sessions[robot_id] = session
        message = VoiceStartMessage(voice_session_id=session.voice_session_id, limits=self._limits)
        if not await _send(connection, message.model_dump(mode="json")):
            session.state = VoiceSessionState.STOPPED
            session.stop_reason = "Could not reach the robot"
            raise VoiceSessionError(502, "Could not reach the robot")
        return session

    def renew(self, voice_session_id: str) -> VoiceSession:
        session = self.get(voice_session_id)
        if session.active:
            session.lease_expires_at = self._clock() + self._lease_seconds
        return session

    async def stop(self, session: VoiceSession, reason: str, *, notify_robot: bool = True) -> None:
        if not session.active:
            return
        session.state = VoiceSessionState.STOPPED
        session.stop_reason = reason
        # A turn still being processed checks `is_current` before replying,
        # so its late result is discarded rather than played.
        session.in_flight_turn = None
        log.info("robot %s: voice session ended: %s", session.robot_id, reason)
        if notify_robot:
            connection = self._connections.get(session.robot_id)
            if connection is not None and connection.generation == session.generation:
                message = VoiceStopMessage(voice_session_id=session.voice_session_id, reason=reason)
                await _send(connection, message.model_dump(mode="json"))

    async def stop_all(self, reason: str) -> None:
        for session in list(self._sessions.values()):
            await self.stop(session, reason)

    async def expire(self) -> None:
        now = self._clock()
        for session in list(self._sessions.values()):
            if not session.active:
                continue
            if now >= session.deadline:
                await self.stop(session, "Maximum conversation length reached")
            elif now >= session.lease_expires_at:
                await self.stop(session, "Owner control stopped responding")
            elif session.in_flight_turn is None and now - session.last_activity >= self._idle_timeout_seconds:
                await self.stop(session, "No speech heard for a while")

    async def on_robot_disconnect(self, connection: RobotConnection) -> None:
        session = self._sessions.get(connection.robot_id)
        if session is not None and session.active and session.generation == connection.generation:
            await self.stop(session, "Robot disconnected", notify_robot=False)

    async def on_robot_message(self, connection: RobotConnection, raw: dict) -> None:
        if raw.get("type") != WSMessageType.VOICE_STATE:
            return
        try:
            message = VoiceStateMessage.model_validate(raw)
        except ValueError:
            return
        session = self._sessions.get(connection.robot_id)
        if (
            session is None
            or not session.active
            or session.generation != connection.generation
            or session.voice_session_id != message.voice_session_id
        ):
            return
        if message.state == RobotVoiceState.LISTENING:
            if session.state in (VoiceSessionState.STARTING, VoiceSessionState.SPEAKING):
                session.state = VoiceSessionState.LISTENING
        elif message.state == RobotVoiceState.SPEAKING:
            session.state = VoiceSessionState.SPEAKING
        elif message.state == RobotVoiceState.ERROR:
            session.last_error = (message.detail or "Robot reported an error")[:200]
        elif message.state == RobotVoiceState.STOPPED:
            await self.stop(session, (message.detail or "Robot stopped listening")[:200], notify_robot=False)

    def begin_turn(self, robot_id: str, generation: int, voice_session_id: str, turn: int) -> VoiceSession:
        session = self._sessions.get(robot_id)
        if session is None or not session.active or session.voice_session_id != voice_session_id:
            raise VoiceSessionError(409, "No active voice session")
        if session.generation != generation:
            raise VoiceSessionError(409, "Stale robot connection")
        if session.in_flight_turn is not None:
            raise VoiceSessionError(409, "A turn is already in progress")
        # Monotonic rather than exact: a robot whose upload was lost in
        # transit has already moved on to the next number.
        if turn < session.next_turn:
            raise VoiceSessionError(409, "Unexpected turn number")
        session.in_flight_turn = turn
        session.next_turn = turn + 1
        session.state = VoiceSessionState.THINKING
        return session

    @staticmethod
    def is_current(session: VoiceSession, turn: int) -> bool:
        return session.active and session.in_flight_turn == turn

    def finish_turn(self, session: VoiceSession, record: VoiceTurnRecord) -> None:
        session.turns.append(record)
        if record.transcript:
            session.last_activity = self._clock()
        if not self.is_current(session, record.turn):
            return
        session.in_flight_turn = None
        if record.outcome == VoiceTurnOutcome.FAILED:
            session.last_error = record.reason
        # SPEAKING until the robot reports its playback finished.
        session.state = (
            VoiceSessionState.SPEAKING if record.outcome == VoiceTurnOutcome.SPOKEN else VoiceSessionState.LISTENING
        )


async def _send(connection: RobotConnection, message: dict) -> bool:
    try:
        async with connection.send_lock:
            await connection.socket.send_json(message)
    except Exception:  # noqa: BLE001 - a dead socket is handled by its own disconnect path
        log.warning("robot %s: could not send voice control message", connection.robot_id)
        return False
    return True


@dataclass
class ConversationReply:
    reply: str
    delivery_channel: Channel


@dataclass
class VoiceTurnPipeline:
    """app.py's existing speech and conversation paths, adapted for this
    module so it never imports app.py (which imports this)."""

    transcribe: Callable[[bytes], Awaitable[str]]
    converse: Callable[[str, str], Awaitable[ConversationReply]]
    session_flags: Callable[[str], Awaitable[tuple[bool, PrivacyContext]]]
    synthesize: Callable[[str], Awaitable[bytes]]
    deliver_private: Callable[[str, Channel, str], Awaitable[bool]]
    speech_withheld_reason: Callable[..., str | None]


def validate_utterance(body: bytes, limits: VoiceLimits) -> None:
    try:
        with wave.open(io.BytesIO(body), "rb") as wav:
            if wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise VoiceSessionError(422, "Utterance must be 16 kHz mono 16-bit WAV")
            # Count the PCM actually present, not the header's frame count.
            duration = len(wav.readframes(wav.getnframes())) / (2 * SAMPLE_RATE)
    except (wave.Error, EOFError) as exc:
        raise VoiceSessionError(422, "Utterance is not a valid WAV file") from exc
    # One second of slack for the pre-roll and chunk rounding.
    if duration > limits.max_utterance_seconds + 1.0:
        raise VoiceSessionError(422, "Utterance is longer than the session limit")


async def run_turn(
    manager: RobotVoiceManager, session: VoiceSession, turn: int, body: bytes, pipeline: VoiceTurnPipeline
) -> tuple[VoiceTurnOutcome, bytes | None]:
    """Transcribe, converse, route and (only if permitted) synthesize one
    turn. Every await is followed by an `is_current` check so a stop that
    lands mid-turn discards the result instead of playing it later."""

    timings: dict[str, object] = {"received_at": datetime.now(UTC)}

    def finish(outcome: VoiceTurnOutcome, **fields) -> VoiceTurnOutcome:
        manager.finish_turn(session, VoiceTurnRecord(turn=turn, outcome=outcome, **timings, **fields))
        return outcome

    def elapsed_ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    try:
        transcript = (await pipeline.transcribe(body)).strip()
    except Exception:
        log.exception("robot voice turn: transcription failed")
        return finish(VoiceTurnOutcome.FAILED, reason="Speech recognition failed"), None
    timings["transcription_ms"] = elapsed_ms(started)
    if not manager.is_current(session, turn):
        return finish(VoiceTurnOutcome.CANCELLED, transcript=transcript or None, reason="Stopped"), None
    if not transcript:
        return finish(VoiceTurnOutcome.NO_SPEECH), None

    started = time.perf_counter()
    try:
        result = await pipeline.converse(session.user_id, transcript)
    except Exception:
        log.exception("robot voice turn: conversation failed")
        return finish(VoiceTurnOutcome.FAILED, transcript=transcript, reason="Companion core did not reply"), None
    timings["conversation_ms"] = elapsed_ms(started)
    if not manager.is_current(session, turn):
        return finish(VoiceTurnOutcome.CANCELLED, transcript=transcript, reply=result.reply, reason="Stopped"), None

    dnd, privacy_context = await pipeline.session_flags(session.user_id)
    withheld = pipeline.speech_withheld_reason(result.delivery_channel, dnd=dnd, privacy_context=privacy_context)
    if withheld is not None:
        reason = withheld
        if result.delivery_channel in (Channel.TELEGRAM, Channel.PHONE):
            delivered = await pipeline.deliver_private(session.user_id, Channel.TELEGRAM, result.reply)
            reason += "; also sent to Telegram" if delivered else "; Telegram is not available"
        return finish(VoiceTurnOutcome.WITHHELD, transcript=transcript, reply=result.reply, reason=reason), None

    started = time.perf_counter()
    try:
        audio = await pipeline.synthesize(result.reply)
    except Exception:
        log.exception("robot voice turn: speech synthesis failed")
        return finish(
            VoiceTurnOutcome.FAILED, transcript=transcript, reply=result.reply, reason="Speech synthesis failed"
        ), None
    timings["synthesis_ms"] = elapsed_ms(started)
    if not manager.is_current(session, turn):
        return finish(VoiceTurnOutcome.CANCELLED, transcript=transcript, reply=result.reply, reason="Stopped"), None
    return finish(VoiceTurnOutcome.SPOKEN, transcript=transcript, reply=result.reply), audio


async def _read_bounded(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise VoiceSessionError(413, "Utterance is too large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise VoiceSessionError(413, "Utterance is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def install_robot_voice_routes(
    app: FastAPI,
    manager: RobotVoiceManager,
    credential_store: RobotCredentialStore,
    require_auth: Callable,
    resolve_user: Callable[[str | None], str],
    pipeline: VoiceTurnPipeline,
    registered_robot_ids: Callable[[], Awaitable[list[str]]],
) -> None:
    owner = [Depends(require_auth)]

    def raise_http(exc: VoiceSessionError) -> HTTPException:
        return HTTPException(exc.status_code, exc.detail)

    @app.get(ROBOT_VOICE, dependencies=owner)
    async def voice_overview() -> VoiceOverview:
        return manager.overview(await registered_robot_ids())

    @app.post(ROBOT_VOICE_START, dependencies=owner)
    async def voice_start(body: StartVoiceRequest) -> VoiceSessionStatus:
        try:
            return manager.status(await manager.start(body.robot_id, resolve_user(body.user_id)))
        except VoiceSessionError as exc:
            raise raise_http(exc) from None

    @app.post(ROBOT_VOICE_RENEW, dependencies=owner)
    async def voice_renew(body: VoiceSessionRef) -> VoiceSessionStatus:
        try:
            return manager.status(manager.renew(body.voice_session_id))
        except VoiceSessionError as exc:
            raise raise_http(exc) from None

    @app.post(ROBOT_VOICE_STOP, dependencies=owner)
    async def voice_stop(body: VoiceSessionRef) -> VoiceSessionStatus:
        try:
            session = manager.get(body.voice_session_id)
        except VoiceSessionError as exc:
            raise raise_http(exc) from None
        await manager.stop(session, "Stopped by owner")
        return manager.status(session)

    @app.post(ROBOT_VOICE_TURN)
    async def robot_voice_turn(request: Request) -> Response:
        robot_id = request.headers.get("x-robot-id")
        authorization = request.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else None
        if not robot_id or not token or not await credential_store.verify(robot_id, token):
            raise HTTPException(401, "Robot authentication failed")
        try:
            generation = int(request.headers.get(ROBOT_GENERATION_HEADER, ""))
            turn = int(request.headers.get(VOICE_TURN_HEADER, ""))
        except ValueError:
            raise HTTPException(422, "Missing robot generation or turn number") from None
        voice_session_id = request.headers.get(VOICE_SESSION_HEADER, "")
        try:
            body = await _read_bounded(request, MAX_UTTERANCE_BYTES)
            session = manager.begin_turn(robot_id, generation, voice_session_id, turn)
        except VoiceSessionError as exc:
            raise raise_http(exc) from None
        try:
            validate_utterance(body, session.limits)
        except VoiceSessionError as exc:
            manager.finish_turn(session, VoiceTurnRecord(turn=turn, outcome=VoiceTurnOutcome.FAILED, reason=exc.detail))
            raise raise_http(exc) from None

        outcome, audio = await run_turn(manager, session, turn, body, pipeline)
        log.info("robot %s: voice turn %s: %s", robot_id, turn, outcome.value)
        headers = {VOICE_OUTCOME_HEADER: outcome.value}
        if outcome == VoiceTurnOutcome.SPOKEN and audio is not None:
            return Response(content=audio, media_type="audio/wav", headers=headers)
        if outcome == VoiceTurnOutcome.FAILED:
            return Response(status_code=502, headers=headers)
        return Response(status_code=204, headers=headers)


async def voice_watchdog_loop(manager: RobotVoiceManager, interval: float = 1.0) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await manager.expire()
        except Exception:
            log.exception("robot voice watchdog tick failed")
