"""Local motion ownership (Phase 24f item 3, ADR 0003 24f amendment).

One owner for every path that moves the robot: the robot voice
conversation, explicit `/behaviour` requests and idle presence. Stop,
standby and shutdown go through `stop()`, which invalidates anything
pending before stopping the daemon move.

While a voice conversation owns motion, explicit and idle behaviours are
rejected, not queued. Conversation transitions are handed to one worker
thread so the voice event loop never blocks on the daemon. Only the latest
transition is kept, so rapid LISTENING/THINKING flips during adaptive
turns collapse into one command. Each transition fully describes the
motion wanted (gesture or none, speech wobble on or off), which is what
makes dropping the superseded ones safe.

A recorded gesture ends at its own final pose, and reachy-mini 1.8.4
starts the next one from its first frame with no blend (24f conformance
record). So while the head is away from home after a gesture, a
conversation transition first returns it home: before the next gesture,
or instead of a plain stop when no gesture follows (speech wobble then
moves around home). Stop, standby, errors and a stopped conversation
still only stop and hold, with no return home.

Both switches are off by default. With both off, ownership is not taken
and every path behaves as before 24f.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Protocol

from reachy_embodiment.state import ServiceState
from shared.models.embodiment import Behaviour, EmbodimentState
from shared.models.motion import MotionSettings, MotionSettingsStatus

log = logging.getLogger(__name__)

# Candidates, per docs/phase-24f.md item 3. Speaking has no recorded move;
# it uses the daemon's speech wobble when that switch is on.
_CONVERSATION_GESTURES: dict[EmbodimentState, Behaviour] = {
    EmbodimentState.LISTENING: Behaviour.LISTENING,
    EmbodimentState.THINKING: Behaviour.THINKING,
}

# How long a return home is given before the next gesture starts: the
# backend's home goto takes 1.0 s.
HOME_SETTLE_SECONDS = 1.2


class MotionBackend(Protocol):
    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None: ...

    def stop_motion(self) -> None: ...

    def goto_home(self) -> None: ...

    def set_speech_wobble(self, enabled: bool) -> None: ...


class MotionController:
    def __init__(
        self,
        backend: MotionBackend,
        state: ServiceState,
        *,
        conversation_motion: bool = False,
        speech_wobble: bool = False,
        threaded: bool = True,
        home_settle_seconds: float = HOME_SETTLE_SECONDS,
    ) -> None:
        """`threaded=False` runs no worker; the caller drives it with
        `run_pending()` (deterministic tests)."""
        self._backend = backend
        self._state = state
        self._conversation_motion = conversation_motion
        self._speech_wobble = speech_wobble
        # `_lock` guards the fields below. `_dispatch_lock` serializes daemon
        # motion calls, so `stop()` waits for an in-flight play and then
        # stops it rather than racing ahead of it.
        self._lock = threading.Condition()
        self._dispatch_lock = threading.Lock()
        self._generation = 0
        self._conversation: int | None = None
        self._last_state: EmbodimentState | None = None
        self._gestured: set[tuple[int, EmbodimentState]] = set()
        self._pending: tuple[int, Callable[[], None]] | None = None
        self._wobbling = False
        self._closed = False
        self._threaded = threaded
        self._worker: threading.Thread | None = None
        self._home_settle_seconds = home_settle_seconds
        # True after a recorded move left the head at its own end pose;
        # cleared by a return home. Only touched with `_dispatch_lock` held.
        self._away_from_home = False
        # Generation of the transition the worker is running.
        self._running_generation = 0

    def settings(self) -> MotionSettingsStatus:
        with self._lock:
            return MotionSettingsStatus(
                conversation_motion=self._conversation_motion,
                speech_wobble=self._speech_wobble,
                conversation_active=self._conversation is not None,
            )

    def configure(self, settings: MotionSettings) -> MotionSettingsStatus:
        # Match the worker's lock ordering. No settings change can race a
        # running transition or the beginning of a voice conversation.
        with self._dispatch_lock, self._lock:
            if self._conversation is not None or self._pending is not None or self._closed:
                raise ValueError("Stop the robot conversation before changing animations")
            if self._wobbling:
                raise ValueError("Speech motion is still active; stop the robot conversation first")
            self._conversation_motion = settings.conversation_motion
            self._speech_wobble = settings.speech_wobble
            return self.settings()

    @property
    def enabled(self) -> bool:
        return self._conversation_motion or self._speech_wobble

    @property
    def conversation_owns_motion(self) -> bool:
        return self.enabled and self._conversation is not None

    def begin_conversation(self) -> int:
        """Starts a conversation's ownership. The returned token fences
        every later call from that conversation."""
        with self._lock:
            self._generation += 1
            token = self._generation
            self._conversation = token
            self._last_state = None
            self._gestured.clear()
        if self.enabled:
            # A move started before the conversation must not keep playing.
            self._submit(token, lambda: self._transition(None, wobble=False))
        return token

    def conversation_state(self, token: int, turn: int, state: EmbodimentState) -> None:
        if not self.enabled:
            return
        with self._lock:
            if token != self._conversation or state == self._last_state:
                return
            self._last_state = state
            if self._state.remote_active:
                return  # remote control owns the robot, not the conversation
            gesture = None
            if self._conversation_motion and state in _CONVERSATION_GESTURES and (turn, state) not in self._gestured:
                # Once per turn: returning to LISTENING after a held segment
                # stops the thinking gesture but does not replay attentive1.
                self._gestured.add((turn, state))
                gesture = _CONVERSATION_GESTURES[state]
            wobble = self._speech_wobble and state == EmbodimentState.SPEAKING
            self._submit_locked(lambda: self._transition(gesture, wobble=wobble))

    def end_conversation(self, token: int, *, completed: bool) -> None:
        """`completed` is a normal end (session limit reached). A stop,
        disconnect or failure passes False and gets no return home."""
        with self._lock:
            if token != self._conversation:
                return
            self._conversation = None
            self._last_state = None
            if not self.enabled:
                return
            home = completed and self._conversation_motion and not self._state.remote_active
            self._submit_locked(lambda: self._end(home=home))

    def request_behaviour(self, behaviour: Behaviour, parameters: dict[str, str], *, idle: bool = False) -> bool:
        """Explicit or idle motion. Returns False when rejected because a
        conversation owns motion. An idle request also yields to pending
        conversation work, e.g. a return home."""
        with self._lock:
            if self.conversation_owns_motion or self._closed:
                return False
            if idle and self._pending is not None:
                return False
            if not idle:
                self._generation += 1
                self._pending = None
                self._lock.notify_all()
        with self._dispatch_lock:
            self._backend.play_behaviour(behaviour, parameters)
            self._away_from_home = True
        return True

    def stop(self) -> None:
        """Invalidates pending motion, then stops the daemon move and speech
        wobble. Ends conversation ownership. Blocks until done."""
        with self._lock:
            self._generation += 1
            self._pending = None
            self._conversation = None
            self._last_state = None
            self._lock.notify_all()  # ends a worker's wait for a return home
        with self._dispatch_lock:
            self._backend.stop_motion()
            self._set_wobble(False, force=True)

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._closed = True
            self._lock.notify_all()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=5.0)

    def _submit(self, token: int, action: Callable[[], None]) -> None:
        with self._lock:
            if token == self._conversation:
                self._submit_locked(action)

    def _submit_locked(self, action: Callable[[], None]) -> None:
        if self._closed:
            return
        self._generation += 1
        self._pending = (self._generation, action)
        if self._threaded and self._worker is None:
            self._worker = threading.Thread(target=self._run, name="motion", daemon=True)
            self._worker.start()
        self._lock.notify_all()

    def _run(self) -> None:
        while self.run_pending(block=True):
            pass

    def run_pending(self, *, block: bool = False) -> bool:
        """Runs the pending transition, if still current. Returns False
        once closed."""
        with self._lock:
            while block and self._pending is None and not self._closed:
                self._lock.wait()
            if self._closed:
                return False
            if self._pending is None:
                return True
            generation, action = self._pending
            self._pending = None
        with self._dispatch_lock:
            with self._lock:
                if generation != self._generation:
                    return True  # superseded or stopped while waiting
                self._running_generation = generation
            try:
                action()
            except Exception:
                log.exception("conversation motion failed")
        return True

    def _transition(self, gesture: Behaviour | None, *, wobble: bool) -> None:
        """A conversation state change. Runs on the worker with
        `_dispatch_lock` held."""
        if not wobble:
            self._set_wobble(False)
        if gesture is not None:
            if self._away_from_home:
                self._go_home()
                if self._superseded_within(self._home_settle_seconds):
                    return  # a newer transition or a stop took over
            self._backend.play_behaviour(gesture, {})  # preempts our previous move
            self._away_from_home = True
        elif self._away_from_home and self._conversation_motion:
            self._go_home()
        else:
            self._backend.stop_motion()
        if wobble:
            self._set_wobble(True)

    def _end(self, *, home: bool) -> None:
        """The conversation ended: one return home after a normal end,
        otherwise stop and hold."""
        self._set_wobble(False)
        if home:
            self._go_home()
        else:
            self._backend.stop_motion()

    def _go_home(self) -> None:
        self._backend.goto_home()  # stops our previous move first
        self._away_from_home = False

    def _superseded_within(self, seconds: float) -> bool:
        """Waits up to `seconds`; True as soon as a newer transition, a
        stop or close makes the running one stale."""
        with self._lock:
            return self._lock.wait_for(
                lambda: self._generation != self._running_generation or self._closed, timeout=seconds
            )

    def _set_wobble(self, enabled: bool, *, force: bool = False) -> None:
        # With the switch off we never enable it, so there is nothing to undo.
        # `force` is for stop: disabling also zeroes the offsets, which
        # 1.8.4's stop_sound leaves applied.
        if not self._speech_wobble or (enabled == self._wobbling and not force):
            return
        try:
            self._backend.set_speech_wobble(enabled)
            self._wobbling = enabled
        except Exception:
            log.exception("speech wobble %s failed", "enable" if enabled else "disable")
