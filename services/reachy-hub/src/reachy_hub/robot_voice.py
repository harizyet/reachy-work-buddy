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

Open-palm stop (Phase 24e item 5, ADR 0023 addendum): with a `PalmStop`,
the robot uploads camera frames to `ROBOT_PALM_FRAME` while a reply plays,
and is told to stop the reply once an open palm is held up. Frames are
classified in memory and dropped.

Adaptive end of turn (Phase 24e, ADR 0023 addendum): a segment whose
transcript sounds unfinished is held instead of answered. The robot either
uploads the next segment of the same turn or asks for the held turn to be
finalized; stop, expiry and disconnect discard held text unanswered.

Wake-started sessions (Phase 24g, ADR 0023 addendum): while the owner has
armed a robot, it monitors for the spoken wake phrase and uploads a
candidate to `ROBOT_WAKE_CANDIDATE`. The hub transcribes it in memory only
to decide relevance; a rejected candidate leaves nothing behind but a
content-free counter. An admitted one opens an ordinary session with no
owner lease, whose first turn reuses the admission transcript. The arm is
persisted and pushed to the robot after every registration.

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
from starlette.requests import ClientDisconnect

from reachy_hub.palm_stop import PalmStop
from reachy_hub.robot_connection_manager import RobotConnection, RobotConnectionManager
from reachy_hub.robot_credential_store import RobotCredentialStore
from reachy_hub.speaker.base import NoSpeakerVerifier
from reachy_hub.turn_completeness import looks_complete
from reachy_hub.wake_arm_store import (
    InMemoryWakeArmStore,
    WakeArm,
    WakeArmStore,
    new_arm,
)
from reachy_hub.wake_relevance import assess
from shared.models.robot_voice import (
    MAX_PALM_FRAME_BYTES,
    MAX_UTTERANCE_BYTES,
    MIN_CONTINUATION_SECONDS,
    ROBOT_GENERATION_HEADER,
    SAMPLE_RATE,
    VOICE_CAPABILITY,
    VOICE_CONTINUATION_CAPABILITY,
    VOICE_OUTCOME_HEADER,
    VOICE_SEGMENT_HEADER,
    VOICE_SESSION_HEADER,
    VOICE_TURN_HEADER,
    WAKE_ARM_HEADER,
    WAKE_CAPABILITY,
    PalmFrameResult,
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
    WakeAdmission,
    WakeArmRequest,
    WakeCounts,
    WakeLimits,
)
from shared.models.robot_ws import (
    VoiceStartMessage,
    VoiceStateMessage,
    VoiceStopMessage,
    WakeArmMessage,
    WSMessageType,
)
from shared.models.session import Channel, PrivacyContext
from shared.models.trust import SpeakerEvidence, VisualEvidence
from shared.models.websearch import TurnWebSearch
from shared.protocols.operator_api import (
    ROBOT_VOICE,
    ROBOT_VOICE_RENEW,
    ROBOT_VOICE_START,
    ROBOT_VOICE_STOP,
    ROBOT_VOICE_WAKE,
)
from shared.protocols.robot_ws import (
    ROBOT_PALM_FRAME,
    ROBOT_VOICE_TURN,
    ROBOT_VOICE_TURN_FINALIZE,
    ROBOT_WAKE_CANDIDATE,
)

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
class HeldTurn:
    """A turn whose transcript so far sounded unfinished."""

    turn: int
    segments: int
    transcript: str
    seconds: float


@dataclass
class VoiceTrustContext:
    """Phase 25a.3: transient, process-local identity evidence attached to
    one voice session — never a second biometric-session store
    (docs/phase-25.md's "Integration into RobotVoiceManager"). Discarded
    with the session; never persisted to the database as authorization.
    `visual` stays unused until Phase 25b's face verification lands."""

    speaker: SpeakerEvidence | None = None
    visual: VisualEvidence | None = None


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
    # Whether the robot can continue a held turn (its capability and a
    # non-zero window); fixed at start.
    continuation: bool = False
    held: HeldTurn | None = None
    # Phase 24g: opened by an admitted wake candidate; no owner lease.
    wake_started: bool = False
    # The admitted request, answered as turn 1 without transcribing the
    # re-uploaded candidate again.
    pretranscribed: str | None = None
    turns: deque[VoiceTurnRecord] = field(default_factory=lambda: deque(maxlen=MAX_TURN_RECORDS))
    # Phase 25a.3: latest identity evidence, overwritten each turn.
    # effective_trust() (reachy_hub/trust.py) re-derives trust from this on
    # every call rather than reading a cached level — see ADR 0024.
    trust: VoiceTrustContext = field(default_factory=VoiceTrustContext)

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
        palm_stop: PalmStop | None = None,
        wake_store: WakeArmStore | None = None,
        wake_limits: WakeLimits | None = None,
    ) -> None:
        self._connections = connections
        self.palm_stop = palm_stop
        self.wake_store: WakeArmStore = wake_store or InMemoryWakeArmStore()
        self.wake_limits = wake_limits or WakeLimits()
        # Write-through copy of the persisted arms, loaded by `load_arms`.
        self._arms: dict[str, WakeArm] = {}
        self._wake_counts: dict[str, WakeCounts] = {}
        # Robots with a candidate being assessed; one at a time each.
        self._candidates: set[str] = set()
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
            wake_started=session.wake_started,
        )

    def overview(self, registered_robot_ids: list[str]) -> VoiceOverview:
        online = {conn.robot_id: conn for conn in self._connections.list_online()}
        robots = [
            RobotVoiceAvailability(
                robot_id=robot_id,
                online=robot_id in online,
                voice_capable=robot_id in online and VOICE_CAPABILITY in online[robot_id].capabilities,
                wake_capable=robot_id in online and WAKE_CAPABILITY in online[robot_id].capabilities,
                wake_armed=robot_id in self._arms,
                wake_counts=self._wake_counts.get(robot_id, WakeCounts()),
            )
            for robot_id in sorted(set(registered_robot_ids) | set(online) | set(self._arms))
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
            continuation=VOICE_CONTINUATION_CAPABILITY in connection.capabilities
            and self._limits.continuation_window_ms > 0,
        )
        self._sessions[robot_id] = session
        message = VoiceStartMessage(
            voice_session_id=session.voice_session_id, limits=self._limits, palm_stop=self.palm_stop is not None
        )
        if not await _send(connection, message.model_dump(mode="json")):
            session.state = VoiceSessionState.STOPPED
            session.stop_reason = "Could not reach the robot"
            raise VoiceSessionError(502, "Could not reach the robot")
        return session

    def renew(self, voice_session_id: str) -> VoiceSession:
        session = self.get(voice_session_id)
        if session.active and not session.wake_started:
            session.lease_expires_at = self._clock() + self._lease_seconds
        return session

    async def stop(self, session: VoiceSession, reason: str, *, notify_robot: bool = True) -> None:
        if not session.active:
            return
        session.state = VoiceSessionState.STOPPED
        session.stop_reason = reason
        # A turn still being processed checks `is_current` before replying,
        # so its late result is discarded rather than played. Held text is
        # dropped, never answered after the session ends.
        session.in_flight_turn = None
        session.held = None
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
            elif not session.wake_started and now >= session.lease_expires_at:
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

    # --- Phase 24g: wake arm and admission ---------------------------------

    async def load_arms(self) -> None:
        self._arms = {arm.robot_id: arm for arm in await self.wake_store.list()}

    def arm_for(self, robot_id: str) -> WakeArm | None:
        return self._arms.get(robot_id)

    async def set_arm(self, robot_id: str, user_id: str, armed: bool) -> None:
        """Owner arm or disarm. Arming again issues a new arm id, so a
        candidate captured under the previous one is refused."""
        if armed:
            arm = new_arm(robot_id, user_id)
            await self.wake_store.set(arm)
            self._arms[robot_id] = arm
        else:
            await self.wake_store.delete(robot_id)
            self._arms.pop(robot_id, None)
            session = self._sessions.get(robot_id)
            if session is not None and session.active and session.wake_started:
                await self.stop(session, "Wake listening turned off")
        log.info("robot %s: wake listening %s", robot_id, "armed" if armed else "disarmed")
        connection = self._connections.get(robot_id)
        if connection is not None:
            await self._send_arm(connection)

    async def on_robot_register(self, connection: RobotConnection) -> None:
        await self._send_arm(connection)

    async def _send_arm(self, connection: RobotConnection) -> None:
        if WAKE_CAPABILITY not in connection.capabilities:
            return
        arm = self._arms.get(connection.robot_id)
        message = WakeArmMessage(arm_id=arm.arm_id if arm else None, limits=self.wake_limits)
        await _send(connection, message.model_dump(mode="json"))

    def count_wake(self, robot_id: str, reason: str) -> None:
        counts = self._wake_counts.setdefault(robot_id, WakeCounts())
        counts.candidates += 1
        if reason == "admitted":
            counts.admitted += 1
        else:
            counts.rejected[reason] = counts.rejected.get(reason, 0) + 1

    def begin_candidate(self, robot_id: str, generation: int, arm_id: str) -> WakeArm | None:
        """Checks the candidate's arm and connection. A stale arm or
        connection is a 409, and the robot stops monitoring under it. None
        means the robot is busy (a session or another candidate), which is
        only a rejection. Pair a returned arm with `end_candidate`."""
        arm = self._arms.get(robot_id)
        if arm is None or arm.arm_id != arm_id:
            raise VoiceSessionError(409, "Wake listening is not armed with this arm")
        connection = self._connections.get(robot_id)
        if connection is None or connection.generation != generation:
            raise VoiceSessionError(409, "Stale robot connection")
        existing = self._sessions.get(robot_id)
        if (existing is not None and existing.active) or robot_id in self._candidates:
            return None
        self._candidates.add(robot_id)
        return arm

    def end_candidate(self, robot_id: str) -> None:
        self._candidates.discard(robot_id)

    async def open_wake_session(self, arm: WakeArm, generation: int, request: str) -> VoiceSession:
        """Opens the admitted candidate's session. Rechecks the arm and
        connection, which may have changed while the candidate was
        transcribed."""
        connection = self._connections.get(arm.robot_id)
        current = self._arms.get(arm.robot_id)
        if current is None or current.arm_id != arm.arm_id:
            raise VoiceSessionError(409, "Wake listening was turned off")
        if connection is None or connection.generation != generation:
            raise VoiceSessionError(409, "Stale robot connection")
        existing = self._sessions.get(arm.robot_id)
        if existing is not None and existing.active:
            raise VoiceSessionError(409, "Robot is already in a voice session")
        now = self._clock()
        deadline = now + self._limits.max_session_seconds
        session = VoiceSession(
            voice_session_id=secrets.token_urlsafe(16),
            robot_id=arm.robot_id,
            user_id=arm.user_id,
            generation=generation,
            limits=self._limits,
            lease_expires_at=deadline,
            deadline=deadline,
            last_activity=now,
            continuation=VOICE_CONTINUATION_CAPABILITY in connection.capabilities
            and self._limits.continuation_window_ms > 0,
            wake_started=True,
            pretranscribed=request,
        )
        self._sessions[arm.robot_id] = session
        message = VoiceStartMessage(
            voice_session_id=session.voice_session_id,
            limits=self._limits,
            palm_stop=self.palm_stop is not None,
            wake_started=True,
            follow_up_seconds=self.wake_limits.follow_up_seconds,
        )
        if not await _send(connection, message.model_dump(mode="json")):
            session.state = VoiceSessionState.STOPPED
            session.stop_reason = "Could not reach the robot"
            raise VoiceSessionError(502, "Could not reach the robot")
        log.info("robot %s: wake admitted, voice session started", arm.robot_id)
        return session

    @staticmethod
    def take_pretranscribed(session: VoiceSession, turn: int, segment: int) -> str | None:
        if turn != 1 or segment != 1 or session.pretranscribed is None:
            return None
        request, session.pretranscribed = session.pretranscribed, None
        return request

    def begin_turn(
        self,
        robot_id: str,
        generation: int,
        voice_session_id: str,
        turn: int,
        segment: int = 1,
        *,
        finalize: bool = False,
    ) -> VoiceSession:
        """Accept a new turn's first segment, the next segment of the held
        turn, or (`finalize`) a request to answer the held turn."""
        session = self._sessions.get(robot_id)
        if session is None or not session.active or session.voice_session_id != voice_session_id:
            raise VoiceSessionError(409, "No active voice session")
        if session.generation != generation:
            raise VoiceSessionError(409, "Stale robot connection")
        if session.in_flight_turn is not None:
            raise VoiceSessionError(409, "A turn is already in progress")
        held = session.held
        if finalize or segment > 1:
            if held is None or held.turn != turn or (not finalize and segment != held.segments + 1):
                raise VoiceSessionError(409, "No held turn to continue")
        else:
            # Monotonic rather than exact: a robot whose upload was lost in
            # transit has already moved on to the next number.
            if turn < session.next_turn:
                raise VoiceSessionError(409, "Unexpected turn number")
            if held is not None:
                # Only after a lost continuation or finalize: the robot has
                # moved on, so the held text is never answered.
                session.turns.append(
                    VoiceTurnRecord(
                        turn=held.turn,
                        transcript=held.transcript,
                        outcome=VoiceTurnOutcome.CANCELLED,
                        reason="Superseded by a new turn",
                        segments=held.segments,
                    )
                )
                session.held = None
            session.next_turn = turn + 1
        session.in_flight_turn = turn
        session.state = VoiceSessionState.THINKING
        return session

    def playing_session(self, robot_id: str, generation: int, voice_session_id: str, turn: int) -> VoiceSession:
        """The session whose reply for `turn` the robot is playing now."""
        session = self._sessions.get(robot_id)
        if session is None or not session.active or session.voice_session_id != voice_session_id:
            raise VoiceSessionError(409, "No active voice session")
        if session.generation != generation:
            raise VoiceSessionError(409, "Stale robot connection")
        last = session.turns[-1] if session.turns else None
        if (
            session.state != VoiceSessionState.SPEAKING
            or last is None
            or last.turn != turn
            or last.outcome != VoiceTurnOutcome.SPOKEN
        ):
            raise VoiceSessionError(409, "No reply is playing")
        return session

    @staticmethod
    def note_palm_stop(session: VoiceSession, turn: int) -> None:
        # The record stays `spoken`: the model's history holds the whole
        # reply, though the listener heard only part of it.
        for record in session.turns:
            if record.turn == turn:
                record.reason = "Stopped by an open palm"

    @staticmethod
    def take_held(session: VoiceSession, turn: int) -> HeldTurn | None:
        held = session.held
        if held is None or held.turn != turn:
            return None
        session.held = None
        return held

    @staticmethod
    def may_hold(session: VoiceSession, seconds: float) -> bool:
        return session.continuation and seconds <= session.limits.max_utterance_seconds - MIN_CONTINUATION_SECONDS

    def hold(self, session: VoiceSession, held: HeldTurn) -> None:
        if not self.is_current(session, held.turn):
            return
        session.held = held
        session.in_flight_turn = None
        session.last_activity = self._clock()
        session.state = VoiceSessionState.LISTENING

    @staticmethod
    def is_current_reply(session: VoiceSession, turn: int) -> bool:
        """The reply for `turn` is still the one playing (no stop landed
        while its frame was being classified)."""
        return (
            session.active
            and session.state == VoiceSessionState.SPEAKING
            and bool(session.turns)
            and session.turns[-1].turn == turn
        )

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
    web_search: TurnWebSearch | None = None


async def _default_verify_speaker(
    wav_bytes: bytes, *, owner_id: str, robot_id: str, voice_session_id: str, turn: int
) -> SpeakerEvidence | None:
    return await NoSpeakerVerifier().verify(
        wav_bytes, owner_id=owner_id, robot_id=robot_id, voice_session_id=voice_session_id, turn=turn
    )


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
    # Phase 25a.3: runs concurrently with `transcribe` on the same WAV
    # (see run_turn below). Defaults to NoSpeakerVerifier — no real
    # adapter is wired into production yet (docs/phase-25.md's
    # dependency-rollout guidance), so voice trust stays capped at T0
    # until 25a.3's model integration replaces this default.
    verify_speaker: Callable[..., Awaitable[SpeakerEvidence | None]] = _default_verify_speaker


def validate_utterance(body: bytes, limits: VoiceLimits) -> float:
    """Check the upload's format and length; returns its duration."""
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
    return duration


async def run_turn(
    manager: RobotVoiceManager,
    session: VoiceSession,
    turn: int,
    body: bytes,
    pipeline: VoiceTurnPipeline,
    *,
    seconds: float = 0.0,
    segment: int = 1,
) -> tuple[VoiceTurnOutcome, bytes | None]:
    """Transcribe one segment, then either hold the turn (it sounds
    unfinished) or answer it. `seconds` is the segment's audio length,
    counted against the merged turn's cap."""

    timings: dict[str, object] = {"received_at": datetime.now(UTC)}
    prior = manager.take_held(session, turn)
    segments = prior.segments + 1 if prior else 1

    def finish(outcome: VoiceTurnOutcome, **fields) -> VoiceTurnOutcome:
        manager.finish_turn(
            session, VoiceTurnRecord(turn=turn, outcome=outcome, segments=segments, **timings, **fields)
        )
        return outcome

    async def verify_speaker() -> SpeakerEvidence | None:
        # Phase 25a.3: the verifier contract says it must never raise, but
        # a broken adapter must still never break the turn — an outage
        # caps trust at T0 (docs/phase-25.md), it doesn't fail the call.
        try:
            return await pipeline.verify_speaker(
                body, owner_id=session.user_id, robot_id=session.robot_id,
                voice_session_id=session.voice_session_id, turn=turn,
            )
        except Exception:
            log.warning("robot voice turn: speaker verification failed", exc_info=True)
            return None

    started = time.perf_counter()
    transcript = manager.take_pretranscribed(session, turn, segment)
    if transcript is None:
        try:
            # Verification runs on the exact admitted utterance, concurrently
            # with STT on the same WAV, never a separately captured sample.
            transcript_result, session.trust.speaker = await asyncio.gather(
                pipeline.transcribe(body), verify_speaker()
            )
        except Exception:
            log.exception("robot voice turn: transcription failed")
            return finish(VoiceTurnOutcome.FAILED, reason="Speech recognition failed"), None
        transcript = transcript_result.strip()
        timings["transcription_ms"] = _elapsed_ms(started)
    else:
        # Phase 24g pretranscribed wake-admission turn: STT already ran
        # during admission, but this is still the first time this turn's
        # audio is available here, so speaker verification still runs on it.
        session.trust.speaker = await verify_speaker()
    merged = " ".join(part for part in (prior.transcript if prior else "", transcript) if part)
    if not manager.is_current(session, turn):
        return finish(VoiceTurnOutcome.CANCELLED, transcript=merged or None, reason="Stopped"), None
    if not merged:
        return finish(VoiceTurnOutcome.NO_SPEECH), None

    total = (prior.seconds if prior else 0.0) + seconds
    # A segment that transcribed to nothing ends the hold: nothing new was said.
    if transcript and manager.may_hold(session, total) and not looks_complete(merged):
        manager.hold(session, HeldTurn(turn=turn, segments=segments, transcript=merged, seconds=total))
        return VoiceTurnOutcome.CONTINUE, None
    return await _answer(manager, session, turn, merged, pipeline, finish)


async def finalize_turn(
    manager: RobotVoiceManager, session: VoiceSession, turn: int, pipeline: VoiceTurnPipeline
) -> tuple[VoiceTurnOutcome, bytes | None]:
    """Answer the held turn: the robot heard no more speech in its window."""

    timings: dict[str, object] = {"received_at": datetime.now(UTC)}
    held = manager.take_held(session, turn)
    if held is None:  # stopped between begin_turn and here
        manager.finish_turn(session, VoiceTurnRecord(turn=turn, outcome=VoiceTurnOutcome.CANCELLED, reason="Stopped"))
        return VoiceTurnOutcome.CANCELLED, None

    def finish(outcome: VoiceTurnOutcome, **fields) -> VoiceTurnOutcome:
        manager.finish_turn(
            session, VoiceTurnRecord(turn=turn, outcome=outcome, segments=held.segments, **timings, **fields)
        )
        return outcome

    return await _answer(manager, session, turn, held.transcript, pipeline, finish)


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


async def _answer(
    manager: RobotVoiceManager,
    session: VoiceSession,
    turn: int,
    transcript: str,
    pipeline: VoiceTurnPipeline,
    finish: Callable[..., VoiceTurnOutcome],
) -> tuple[VoiceTurnOutcome, bytes | None]:
    """Converse, route and (only if permitted) synthesize. Every await is
    followed by an `is_current` check so a stop that lands mid-turn
    discards the result instead of playing it later. `finish` records the
    turn along with the caller's stage timings."""

    timings: dict[str, object] = {}
    started = time.perf_counter()
    try:
        result = await pipeline.converse(session.user_id, transcript)
    except Exception:
        log.exception("robot voice turn: conversation failed")
        return finish(VoiceTurnOutcome.FAILED, transcript=transcript, reason="Companion core did not reply"), None
    timings["conversation_ms"] = _elapsed_ms(started)
    timings["web_search"] = result.web_search
    if not manager.is_current(session, turn):
        return finish(
            VoiceTurnOutcome.CANCELLED, transcript=transcript, reply=result.reply, reason="Stopped", **timings
        ), None

    dnd, privacy_context = await pipeline.session_flags(session.user_id)
    withheld = pipeline.speech_withheld_reason(result.delivery_channel, dnd=dnd, privacy_context=privacy_context)
    if withheld is not None:
        reason = withheld
        if result.delivery_channel in (Channel.TELEGRAM, Channel.PHONE):
            delivered = await pipeline.deliver_private(session.user_id, Channel.TELEGRAM, result.reply)
            reason += "; also sent to Telegram" if delivered else "; Telegram is not available"
        return finish(
            VoiceTurnOutcome.WITHHELD, transcript=transcript, reply=result.reply, reason=reason, **timings
        ), None

    started = time.perf_counter()
    try:
        audio = await pipeline.synthesize(result.reply)
    except Exception:
        log.exception("robot voice turn: speech synthesis failed")
        return finish(
            VoiceTurnOutcome.FAILED,
            transcript=transcript,
            reply=result.reply,
            reason="Speech synthesis failed",
            **timings,
        ), None
    timings["synthesis_ms"] = _elapsed_ms(started)
    if not manager.is_current(session, turn):
        return finish(
            VoiceTurnOutcome.CANCELLED, transcript=transcript, reply=result.reply, reason="Stopped", **timings
        ), None
    return finish(VoiceTurnOutcome.SPOKEN, transcript=transcript, reply=result.reply, **timings), audio


async def _read_bounded(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise VoiceSessionError(413, "Upload is too large")
    chunks: list[bytes] = []
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise VoiceSessionError(413, "Upload is too large")
            chunks.append(chunk)
    except ClientDisconnect:
        # The robot cancels an in-flight palm frame when playback ends; the
        # reply goes nowhere, so this only keeps it out of the error log.
        raise VoiceSessionError(400, "Upload was interrupted") from None
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

    @app.post(ROBOT_VOICE_WAKE, dependencies=owner)
    async def voice_wake(body: WakeArmRequest) -> VoiceOverview:
        await manager.set_arm(body.robot_id, resolve_user(body.user_id), body.armed)
        return manager.overview(await registered_robot_ids())

    @app.post(ROBOT_VOICE_STOP, dependencies=owner)
    async def voice_stop(body: VoiceSessionRef) -> VoiceSessionStatus:
        try:
            session = manager.get(body.voice_session_id)
        except VoiceSessionError as exc:
            raise raise_http(exc) from None
        await manager.stop(session, "Stopped by owner")
        return manager.status(session)

    async def authenticated_robot(request: Request) -> str:
        robot_id = request.headers.get("x-robot-id")
        authorization = request.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else None
        if not robot_id or not token or not await credential_store.verify(robot_id, token):
            raise HTTPException(401, "Robot authentication failed")
        return robot_id

    async def robot_turn_headers(request: Request) -> tuple[str, int, str, int, int]:
        robot_id = await authenticated_robot(request)
        try:
            generation = int(request.headers.get(ROBOT_GENERATION_HEADER, ""))
            turn = int(request.headers.get(VOICE_TURN_HEADER, ""))
            segment = int(request.headers.get(VOICE_SEGMENT_HEADER, "1"))
        except ValueError:
            raise HTTPException(422, "Missing robot generation or turn number") from None
        if segment < 1:
            raise HTTPException(422, "Invalid segment number")
        return robot_id, generation, request.headers.get(VOICE_SESSION_HEADER, ""), turn, segment

    def turn_response(robot_id: str, turn: int, outcome: VoiceTurnOutcome, audio: bytes | None) -> Response:
        log.info("robot %s: voice turn %s: %s", robot_id, turn, outcome.value)
        headers = {VOICE_OUTCOME_HEADER: outcome.value}
        if outcome == VoiceTurnOutcome.SPOKEN and audio is not None:
            return Response(content=audio, media_type="audio/wav", headers=headers)
        if outcome == VoiceTurnOutcome.FAILED:
            return Response(status_code=502, headers=headers)
        return Response(status_code=204, headers=headers)

    @app.post(ROBOT_VOICE_TURN)
    async def robot_voice_turn(request: Request) -> Response:
        robot_id, generation, voice_session_id, turn, segment = await robot_turn_headers(request)
        try:
            body = await _read_bounded(request, MAX_UTTERANCE_BYTES)
            session = manager.begin_turn(robot_id, generation, voice_session_id, turn, segment)
        except VoiceSessionError as exc:
            raise raise_http(exc) from None
        try:
            seconds = validate_utterance(body, session.limits)
            held_seconds = session.held.seconds if session.held and session.held.turn == turn else 0.0
            if held_seconds + seconds > session.limits.max_utterance_seconds + 1.0:
                raise VoiceSessionError(422, "Utterance is longer than the session limit")
        except VoiceSessionError as exc:
            manager.take_held(session, turn)
            manager.finish_turn(session, VoiceTurnRecord(turn=turn, outcome=VoiceTurnOutcome.FAILED, reason=exc.detail))
            raise raise_http(exc) from None

        outcome, audio = await run_turn(manager, session, turn, body, pipeline, seconds=seconds, segment=segment)
        return turn_response(robot_id, turn, outcome, audio)

    def reject_candidate(robot_id: str, reason: str) -> Response:
        # Never the transcript: only the reason is kept or logged.
        manager.count_wake(robot_id, reason)
        log.info("robot %s: wake candidate rejected: %s", robot_id, reason)
        return Response(status_code=204, headers={VOICE_OUTCOME_HEADER: VoiceTurnOutcome.REJECTED.value})

    @app.post(ROBOT_WAKE_CANDIDATE)
    async def robot_wake_candidate(request: Request) -> Response:
        robot_id = await authenticated_robot(request)
        try:
            generation = int(request.headers.get(ROBOT_GENERATION_HEADER, ""))
        except ValueError:
            raise HTTPException(422, "Missing robot generation") from None
        try:
            body = await _read_bounded(request, MAX_UTTERANCE_BYTES)
            arm = manager.begin_candidate(robot_id, generation, request.headers.get(WAKE_ARM_HEADER, ""))
        except VoiceSessionError as exc:
            raise raise_http(exc) from None
        if arm is None:
            return reject_candidate(robot_id, "busy")
        try:
            validate_utterance(body, VoiceLimits(max_utterance_seconds=manager.wake_limits.max_candidate_seconds))
            reason, request_text = await _assess_candidate(arm, body, pipeline)
            del body
            if reason == "admitted":
                session = await manager.open_wake_session(arm, generation, request_text)
                manager.count_wake(robot_id, reason)
                return Response(
                    content=WakeAdmission(voice_session_id=session.voice_session_id).model_dump_json(),
                    media_type="application/json",
                )
        except VoiceSessionError as exc:
            if exc.status_code != 409:
                raise raise_http(exc) from None
            # The arm, connection or robot changed while it was assessed.
            reason = "busy"
        finally:
            manager.end_candidate(robot_id)
        return reject_candidate(robot_id, reason)

    @app.post(ROBOT_PALM_FRAME)
    async def robot_palm_frame(request: Request) -> PalmFrameResult:
        robot_id, generation, voice_session_id, turn, _ = await robot_turn_headers(request)
        if manager.palm_stop is None:
            raise HTTPException(404, "Open-palm stop is not enabled")
        try:
            body = await _read_bounded(request, MAX_PALM_FRAME_BYTES)
            session = manager.playing_session(robot_id, generation, voice_session_id, turn)
        except VoiceSessionError as exc:
            raise raise_http(exc) from None
        stop = await manager.palm_stop.check(voice_session_id, turn, body)
        if stop and manager.is_current_reply(session, turn):
            manager.note_palm_stop(session, turn)
            log.info("robot %s: voice turn %s: open palm, stopping the reply", robot_id, turn)
            return PalmFrameResult(stop=True)
        return PalmFrameResult(stop=False)

    @app.post(ROBOT_VOICE_TURN_FINALIZE)
    async def robot_voice_turn_finalize(request: Request) -> Response:
        robot_id, generation, voice_session_id, turn, _ = await robot_turn_headers(request)
        try:
            session = manager.begin_turn(robot_id, generation, voice_session_id, turn, finalize=True)
        except VoiceSessionError as exc:
            raise raise_http(exc) from None
        outcome, audio = await finalize_turn(manager, session, turn, pipeline)
        return turn_response(robot_id, turn, outcome, audio)


async def _assess_candidate(arm: WakeArm, body: bytes, pipeline: VoiceTurnPipeline) -> tuple[str, str]:
    """(reason, request): "admitted" with the request text, or why not.
    The transcript lives only in this call's locals."""
    dnd, privacy_context = await pipeline.session_flags(arm.user_id)
    if dnd or privacy_context == PrivacyContext.MEETING:
        return "do_not_disturb", ""
    try:
        transcript = (await pipeline.transcribe(body)).strip()
    except Exception:
        log.exception("robot %s: wake candidate transcription failed", arm.robot_id)
        return "stt_failed", ""
    relevance = assess(transcript)
    return relevance.reason, relevance.request


async def voice_watchdog_loop(manager: RobotVoiceManager, interval: float = 1.0) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await manager.expire()
        except Exception:
            log.exception("robot voice watchdog tick failed")
