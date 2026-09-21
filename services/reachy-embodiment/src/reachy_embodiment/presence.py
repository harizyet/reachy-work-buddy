"""Local presence loop and offline-fallback state machine.

See docs/adr/0004-offline-fallback.md. Runs independently of companion-core
and reachy-hub, on its own thread inside reachy-embodiment, so Reachy stays
animated (idle behaviours) and keeps its own connectivity judgement even when
the homelab is completely unreachable. Adapted in spirit from Jarvis's
presence.py (30Hz independent thread, LLM/hub never touches it directly, it
only reacts to signals) — see docs/jarvis-baseline.md.

Two independent things happen on every tick:

1. Watchdog: if no heartbeat (explicit POST /heartbeat, or any inbound
   POST /behaviour/{name}, which is itself proof reachy-hub is alive) has
   been seen within `heartbeat_timeout` seconds, transition to DISCONNECTED.
   Receiving a heartbeat while DISCONNECTED transitions back to IDLE.
2. Idle animation: while the standing state is IDLE or DISCONNECTED (i.e.
   not being actively driven by a companion-core-issued behaviour), cycle
   through the local idle behaviour set every `idle_cycle_seconds` so the
   robot never goes fully static.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from reachy_embodiment.robot import RobotBackend
from reachy_embodiment.state import ServiceState
from shared.models.embodiment import Behaviour, EmbodimentState

log = logging.getLogger(__name__)

IDLE_CYCLE = (Behaviour.IDLE_BREATHING, Behaviour.SUBTLE_SCAN, Behaviour.ANTENNA_TWITCH)

# States actively driven by an explicit companion-core behaviour command;
# the presence loop must not override these with idle animation.
_HOMELAB_DRIVEN_STATES = frozenset(
    {
        EmbodimentState.LISTENING,
        EmbodimentState.THINKING,
        EmbodimentState.SPEAKING,
        EmbodimentState.REMOTE,
        EmbodimentState.SLEEP,
    }
)


class PresenceLoop:
    def __init__(
        self,
        backend: RobotBackend,
        state: ServiceState,
        heartbeat_timeout: float = 5.0,
        idle_cycle_seconds: float = 3.0,
        tick_hz: float = 30.0,
    ) -> None:
        self._backend = backend
        self._state = state
        self._heartbeat_timeout = heartbeat_timeout
        self._idle_cycle_seconds = idle_cycle_seconds
        self._tick_interval = 1.0 / tick_hz

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._last_heartbeat_at = datetime.now(UTC)
        self._last_idle_tick_monotonic = 0.0
        self._idle_index = 0

    def start(self) -> None:
        self._last_heartbeat_at = datetime.now(UTC)
        self._state.last_heartbeat_at = self._last_heartbeat_at
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._tick_interval * 5)
            self._thread = None

    def heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat_at = datetime.now(UTC)
            self._state.last_heartbeat_at = self._last_heartbeat_at
            if self._state.embodiment_state == EmbodimentState.DISCONNECTED:
                log.info("heartbeat resumed, leaving DISCONNECTED -> IDLE")
                self._state.embodiment_state = EmbodimentState.IDLE

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.tick(datetime.now(UTC), time.monotonic())
            self._stop_event.wait(self._tick_interval)

    def tick(self, now: datetime, monotonic_now: float) -> None:
        """One presence-loop step. Exposed directly so tests can drive it
        deterministically without depending on real wall-clock sleeps."""
        with self._lock:
            self._check_watchdog(now)
            self._maybe_play_idle(monotonic_now)

    def _check_watchdog(self, now: datetime) -> None:
        elapsed = (now - self._last_heartbeat_at).total_seconds()
        if elapsed > self._heartbeat_timeout and self._state.embodiment_state != EmbodimentState.DISCONNECTED:
            log.warning("no heartbeat for %.1fs, entering DISCONNECTED", elapsed)
            self._state.embodiment_state = EmbodimentState.DISCONNECTED

    def _maybe_play_idle(self, monotonic_now: float) -> None:
        if self._state.embodiment_state in _HOMELAB_DRIVEN_STATES:
            return
        if monotonic_now - self._last_idle_tick_monotonic < self._idle_cycle_seconds:
            return

        self._last_idle_tick_monotonic = monotonic_now
        behaviour = IDLE_CYCLE[self._idle_index % len(IDLE_CYCLE)]
        self._idle_index += 1

        self._backend.play_behaviour(behaviour, {})
        self._state.last_behaviour = behaviour
        self._state.last_behaviour_at = datetime.now(UTC)
        # Idle-cycle behaviours are animation only. The standing state here
        # is already IDLE or DISCONNECTED (that's the guard above); don't
        # let STATE_FOR_BEHAVIOUR's IDLE mapping clobber a DISCONNECTED
        # watchdog trip back to IDLE.
