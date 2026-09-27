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

Listening and thinking are short, silent goto poses held until the
state changes, not recorded moves: every recorded emotion move plays a
sound the daemon cannot mute, which the microphone captured as speech,
and they run 4-6 s (24f physical record, 2026-09-27). A goto starts from
the current pose, so poses follow each other with no return home. Each
pose varies a little per turn, and returning to a state within the same
turn reuses that turn's pose. When no pose follows (speaking), the head
returns home, and speech wobble then moves around home. Stop, standby,
errors and a stopped conversation still only stop and hold, with no
return home.

Both switches are off by default. With both off, ownership is not taken
and every path behaves as before 24f.

Phase 24g adds a third switch, `wake_animation` (on by default, owner
decision 2026-09-27). While wake monitoring is armed:
- the robot rests in the daemon's sleep pose between conversations;
- a detected wake phrase lifts the head slightly to an alert pose, a quick
  cue to go on speaking;
- an admitted conversation brings the head up to home.

Every rest move is a silent goto. The daemon's own routines are not used:
- **Wake-up** plays a sound the microphone recorded into the candidate, and
  lasts long enough that people waited for it and missed their window.
- **Go-to-sleep** plays its snore every time, which made every false wake
  audible.

Both were found in the 24g first physical run. From an unknown pose, the
head goes home first and then down, the path the daemon's go-to-sleep
takes.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Literal, Protocol

from reachy_embodiment.robot import HOME_GOTO
from reachy_embodiment.state import ServiceState
from shared.models.embodiment import Behaviour, EmbodimentState
from shared.models.motion import MotionSettings, MotionSettingsStatus

log = logging.getLogger(__name__)

# Conversation poses, in the daemon's units: head roll/pitch/yaw in
# radians (negative pitch looks up), antennas [right, left] in radians.
# Home antennas are [-0.1745, 0.1745]; +right / -left perks an antenna up,
# -right / +left folds it back. Tuned on nano-1 with the owner watching
# (2026-09-27): the first, smaller candidates were too subtle.
LISTEN_DURATION = 0.5
LISTEN_ROLL = (0.28, 0.34)  # tilt to a random side
LISTEN_YAW = 0.06  # +/- random
LISTEN_ANTENNA = 0.25  # both perked
THINK_DURATION = 0.8
THINK_YAW = (0.36, 0.42)  # glance to a random side
THINK_PITCH = (-0.24, -0.19)  # and up
THINK_ROLL = (0.08, 0.11)  # against the glance
THINK_ANTENNA_BACK = 0.50  # the glance side's antenna folds back
THINK_ANTENNA_PERKED = 0.25  # the other one perks
ANTENNA_JITTER = 0.05

# Phase 24g rest poses, outside the conversation clamp below: the daemon's
# own sleep pose (reachy_mini 1.8.4 SLEEP_HEAD_POSE, pitched down 0.426 rad,
# and SLEEP_ANTENNAS_JOINT_POSITIONS), and an alert pose about a third of
# the way from it towards home with the antennas lifted a little.
SLEEP_POSE: dict[str, object] = {
    "head_pose": {"x": -0.021, "y": 0.0, "z": -0.044, "roll": 0.0, "pitch": 0.4257, "yaw": 0.0},
    "antennas": [-3.05, 3.05],
    "body_yaw": 0.0,
    "duration": 1.0,
}
ALERT_POSE: dict[str, object] = {
    "head_pose": {"x": -0.014, "y": 0.0, "z": -0.029, "roll": 0.0, "pitch": 0.28, "yaw": 0.0},
    "antennas": [-2.4, 2.4],
    "body_yaw": 0.0,
    "duration": 0.5,
}

RestPose = Literal["sleep", "alert", "home"]

# Hard bounds every pose is clamped to, whatever the constants above say.
MAX_ROLL = 0.40
MAX_PITCH = 0.30
MAX_YAW = 0.45
MAX_ANTENNA = 0.60


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _pose(roll: float, pitch: float, yaw: float, antennas: tuple[float, float], duration: float) -> dict[str, object]:
    return {
        "head_pose": {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
            "roll": round(_clamp(roll, MAX_ROLL), 4),
            "pitch": round(_clamp(pitch, MAX_PITCH), 4),
            "yaw": round(_clamp(yaw, MAX_YAW), 4),
        },
        "antennas": [round(_clamp(a, MAX_ANTENNA), 4) for a in antennas],
        "body_yaw": 0.0,
        "duration": duration,
    }


def listening_pose(rng: random.Random) -> dict[str, object]:
    side = rng.choice((-1, 1))
    return _pose(
        roll=side * rng.uniform(*LISTEN_ROLL),
        pitch=0.0,
        yaw=rng.uniform(-LISTEN_YAW, LISTEN_YAW),
        antennas=(
            LISTEN_ANTENNA + rng.uniform(-ANTENNA_JITTER, ANTENNA_JITTER),
            -LISTEN_ANTENNA + rng.uniform(-ANTENNA_JITTER, ANTENNA_JITTER),
        ),
        duration=LISTEN_DURATION,
    )


def thinking_pose(rng: random.Random) -> dict[str, object]:
    side = rng.choice((-1, 1))
    if side > 0:  # glance with positive yaw: right folds back
        antennas = (-THINK_ANTENNA_BACK, -THINK_ANTENNA_PERKED)
    else:
        antennas = (THINK_ANTENNA_PERKED, THINK_ANTENNA_BACK)
    return _pose(
        roll=-side * rng.uniform(*THINK_ROLL),
        pitch=rng.uniform(*THINK_PITCH),
        yaw=side * rng.uniform(*THINK_YAW),
        antennas=antennas,
        duration=THINK_DURATION,
    )


# Speaking has no pose; it uses the daemon's speech wobble when that
# switch is on.
_CONVERSATION_POSES: dict[EmbodimentState, Callable[[random.Random], dict[str, object]]] = {
    EmbodimentState.LISTENING: listening_pose,
    EmbodimentState.THINKING: thinking_pose,
}


class MotionBackend(Protocol):
    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> bool | None: ...

    def stop_motion(self) -> None: ...

    def goto_home(self) -> None: ...

    def goto_pose(self, pose: dict[str, object]) -> None: ...

    def set_speech_wobble(self, enabled: bool) -> None: ...


class MotionController:
    def __init__(
        self,
        backend: MotionBackend,
        state: ServiceState,
        *,
        conversation_motion: bool = False,
        speech_wobble: bool = False,
        wake_animation: bool = False,
        threaded: bool = True,
        rng: random.Random | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """`threaded=False` runs no worker; the caller drives it with
        `run_pending()` (deterministic tests)."""
        self._backend = backend
        self._state = state
        self._conversation_motion = conversation_motion
        self._speech_wobble = speech_wobble
        self._wake_animation = wake_animation
        # `_lock` guards the fields below. `_dispatch_lock` serializes daemon
        # motion calls, so `stop()` waits for an in-flight play and then
        # stops it rather than racing ahead of it.
        self._lock = threading.Condition()
        self._dispatch_lock = threading.Lock()
        self._generation = 0
        self._conversation: int | None = None
        self._last_state: EmbodimentState | None = None
        # This conversation's pose per (turn, state), so a held segment
        # returns to the same listening pose.
        self._turn_poses: dict[tuple[int, EmbodimentState], dict[str, object]] = {}
        self._rng = rng or random.Random()
        self._pending: tuple[int, Callable[[], None]] | None = None
        self._wobbling = False
        self._closed = False
        self._threaded = threaded
        self._worker: threading.Thread | None = None
        # True after a pose or recorded move left the head away from home;
        # cleared by a return home. Only touched with `_dispatch_lock` held.
        self._away_from_home = False
        # Phase 24g: "sleep", "alert" or "home" while the head is known to
        # hold that pose; any other motion or a stop forgets it.
        self._rest_pose: RestPose | None = None
        self._sleep = sleep

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
            self._turn_poses.clear()
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
            pose = None
            if self._conversation_motion and state in _CONVERSATION_POSES:
                pose = self._turn_poses.get((turn, state))
                if pose is None:
                    pose = _CONVERSATION_POSES[state](self._rng)
                    self._turn_poses[(turn, state)] = pose
            wobble = self._speech_wobble and state == EmbodimentState.SPEAKING
            self._submit_locked(lambda: self._transition(pose, wobble=wobble))

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
            # Idle presence asks every few seconds for behaviours that map
            # to no move; only a move that started leaves the rest pose.
            if self._backend.play_behaviour(behaviour, parameters) is not False:
                self._away_from_home = True
                self._rest_pose = None
        return True

    def rest_move(self, pose: RestPose) -> bool:
        """Phase 24g: "alert" for a detected wake phrase, "home" for an
        admitted conversation, or "sleep" while monitoring between
        conversations. Blocks until the daemon accepts the move (from an
        unknown pose, until the head is home). False when the switch is
        off, or when a conversation or remote control owns motion."""
        if not self._wake_animation:
            return False
        with self._lock:
            if self.conversation_owns_motion or self._closed or self._state.remote_active:
                return False
            self._generation += 1
            self._pending = None
            self._lock.notify_all()
        with self._dispatch_lock:
            self._set_wobble(False)
            if pose == "home":
                self._backend.goto_home()
            elif pose == "alert":
                self._backend.goto_pose(ALERT_POSE)
            else:
                if self._rest_pose is None:
                    # Unknown pose: home first, then down. A goto preempts
                    # the previous one, so the first has to finish.
                    self._backend.goto_home()
                    self._sleep(float(HOME_GOTO["duration"]) + 0.2)
                self._backend.goto_pose(SLEEP_POSE)
            self._rest_pose = pose
            self._away_from_home = pose != "home"
        return True

    def stop(self) -> None:
        """Invalidates pending motion, then stops the daemon move and speech
        wobble. Ends conversation ownership. Blocks until done."""
        with self._lock:
            self._generation += 1
            self._pending = None
            self._conversation = None
            self._last_state = None
            self._lock.notify_all()
        with self._dispatch_lock:
            self._backend.stop_motion()
            self._set_wobble(False, force=True)
            self._rest_pose = None

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
            try:
                action()
            except Exception:
                log.exception("conversation motion failed")
        return True

    def _transition(self, pose: dict[str, object] | None, *, wobble: bool) -> None:
        """A conversation state change. Runs on the worker with
        `_dispatch_lock` held."""
        if not wobble:
            self._set_wobble(False)
        if pose is not None:
            self._backend.goto_pose(pose)  # preempts our previous move
            self._away_from_home = True
            self._rest_pose = None
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
        self._rest_pose = None

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
