import random
import threading

from reachy_embodiment.motion import (
    LISTEN_DURATION,
    MAX_ANTENNA,
    MAX_PITCH,
    MAX_ROLL,
    MAX_YAW,
    THINK_DURATION,
    MotionController,
    listening_pose,
    thinking_pose,
)
from reachy_embodiment.state import ServiceState

from shared.models.embodiment import Behaviour, EmbodimentState

LISTENING = EmbodimentState.LISTENING
THINKING = EmbodimentState.THINKING
SPEAKING = EmbodimentState.SPEAKING


_POSE_KINDS = {LISTEN_DURATION: "listen", THINK_DURATION: "think", 1.5: "sweep"}
LISTEN = ("pose", "listen")
THINK = ("pose", "think")


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.poses: list[dict] = []

    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None:
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5.0)
        self.calls.append(("play", name))

    def stop_motion(self) -> None:
        self.calls.append(("stop",))

    def goto_home(self) -> None:
        self.calls.append(("home",))

    def goto_pose(self, pose: dict) -> None:
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5.0)
        self.calls.append(("pose", _POSE_KINDS[pose["duration"]]))
        self.poses.append(pose)

    def set_speech_wobble(self, enabled: bool) -> None:
        self.calls.append(("wobble", enabled))


def make(**kwargs) -> tuple[MotionController, FakeBackend, ServiceState]:
    backend = FakeBackend()
    state = ServiceState()
    kwargs.setdefault("threaded", False)
    return MotionController(backend, state, **kwargs), backend, state


def step(ctl: MotionController, backend: FakeBackend) -> list[tuple]:
    backend.calls.clear()
    ctl.run_pending()
    return list(backend.calls)


def test_disabled_sends_nothing_and_takes_no_ownership() -> None:
    ctl, backend, _ = make()
    token = ctl.begin_conversation()
    ctl.conversation_state(token, 1, LISTENING)
    ctl.run_pending()
    assert backend.calls == []
    assert ctl.request_behaviour(Behaviour.GREETING, {}) is True
    assert backend.calls == [("play", Behaviour.GREETING)]
    ctl.end_conversation(token, completed=True)
    ctl.run_pending()
    assert backend.calls == [("play", Behaviour.GREETING)]


def test_begin_stops_a_move_started_before_the_conversation() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    ctl.begin_conversation()
    assert step(ctl, backend) == [("stop",)]


def test_each_state_goes_straight_to_its_pose() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.run_pending()

    ctl.conversation_state(token, 1, LISTENING)
    assert step(ctl, backend) == [LISTEN]
    # A goto starts from the current pose: no return home in between.
    ctl.conversation_state(token, 1, THINKING)
    assert step(ctl, backend) == [THINK]
    # Speaking has no pose, so the head returns home.
    ctl.conversation_state(token, 1, SPEAKING)
    assert step(ctl, backend) == [("home",)]
    ctl.conversation_state(token, 2, LISTENING)
    assert step(ctl, backend) == [LISTEN]
    assert ("play", Behaviour.LISTENING) not in backend.calls  # no recorded, sounding move


def test_held_segment_returns_to_the_same_turns_pose() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.run_pending()
    for state in (LISTENING, THINKING, LISTENING, THINKING):
        ctl.conversation_state(token, 1, state)
        ctl.run_pending()
    assert backend.poses[2] == backend.poses[0]
    assert backend.poses[3] == backend.poses[1]
    ctl.conversation_state(token, 2, LISTENING)
    ctl.run_pending()
    # A new turn draws a new pose (the rng makes an identical one unlikely).
    assert backend.poses[4] != backend.poses[0]


def test_poses_vary_and_stay_within_bounds() -> None:
    rng = random.Random(7)
    for make_pose in (listening_pose, thinking_pose):
        poses = [make_pose(rng) for _ in range(200)]
        assert len({str(p) for p in poses}) > 150
        for pose in poses:
            head = pose["head_pose"]
            assert abs(head["roll"]) <= MAX_ROLL
            assert abs(head["pitch"]) <= MAX_PITCH
            assert abs(head["yaw"]) <= MAX_YAW
            assert (head["x"], head["y"], head["z"]) == (0.0, 0.0, 0.0)
            assert all(abs(a) <= MAX_ANTENNA for a in pose["antennas"])
            assert pose["body_yaw"] == 0.0
            assert 0 < pose["duration"] <= 1.0
        # Both sides are used.
        assert {p["head_pose"]["roll"] > 0 for p in poses} == {True, False}


def test_thinking_looks_up_and_folds_back_the_glance_side_antenna() -> None:
    # Owner-tuned on nano-1: negative pitch is up; +right/-left perks an
    # antenna, -right/+left folds it back.
    rng = random.Random(11)
    for _ in range(50):
        pose = thinking_pose(rng)
        head, (right, left) = pose["head_pose"], pose["antennas"]
        assert head["pitch"] < 0
        assert head["roll"] * head["yaw"] < 0  # tilts against the glance
        if head["yaw"] > 0:
            assert (right, left) == (-0.5, -0.25)
        else:
            assert (right, left) == (0.25, 0.5)
        listen = listening_pose(rng)["antennas"]
        assert listen[0] > 0 > listen[1]  # both perked


def test_speaking_after_a_gesture_returns_home_before_wobble() -> None:
    ctl, backend, _ = make(conversation_motion=True, speech_wobble=True)
    token = ctl.begin_conversation()
    ctl.run_pending()
    ctl.conversation_state(token, 1, THINKING)
    ctl.run_pending()
    ctl.conversation_state(token, 1, SPEAKING)
    assert step(ctl, backend) == [("home",), ("wobble", True)]


def test_conversation_start_after_an_explicit_behaviour_returns_home() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    ctl.request_behaviour(Behaviour.GREETING, {})
    ctl.begin_conversation()
    assert step(ctl, backend) == [("home",)]


def test_repeated_state_report_does_not_restart() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.run_pending()
    ctl.conversation_state(token, 1, LISTENING)
    ctl.run_pending()
    ctl.conversation_state(token, 2, LISTENING)
    assert step(ctl, backend) == []


def test_rapid_transitions_coalesce_to_the_latest() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.conversation_state(token, 1, LISTENING)
    ctl.conversation_state(token, 1, THINKING)
    assert step(ctl, backend) == [THINK]


def test_explicit_behaviour_rejected_while_conversation_owns_motion() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    assert ctl.request_behaviour(Behaviour.GREETING, {}) is False
    assert ctl.request_behaviour(Behaviour.IDLE_BREATHING, {}, idle=True) is False
    ctl.end_conversation(token, completed=False)
    ctl.run_pending()
    backend.calls.clear()
    assert ctl.request_behaviour(Behaviour.GREETING, {}) is True
    # Nothing was queued to play after the conversation.
    assert backend.calls == [("play", Behaviour.GREETING)]


def test_normal_end_returns_home_once_and_stop_end_holds() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.conversation_state(token, 1, THINKING)
    ctl.run_pending()
    ctl.end_conversation(token, completed=True)
    assert step(ctl, backend) == [("home",)]
    ctl.end_conversation(token, completed=True)
    assert step(ctl, backend) == []

    token = ctl.begin_conversation()
    ctl.run_pending()
    ctl.conversation_state(token, 1, THINKING)
    ctl.run_pending()
    ctl.end_conversation(token, completed=False)
    assert step(ctl, backend) == [("stop",)]  # a stopped conversation holds its pose


def test_new_conversation_drops_a_pending_return_home() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.end_conversation(token, completed=True)
    ctl.begin_conversation()
    assert step(ctl, backend) == [("stop",)]


def test_idle_yields_to_pending_return_home() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.end_conversation(token, completed=True)
    assert ctl.request_behaviour(Behaviour.IDLE_BREATHING, {}, idle=True) is False
    assert step(ctl, backend) == [("home",)]


def test_explicit_behaviour_cancels_a_pending_return_home() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.end_conversation(token, completed=True)
    assert ctl.request_behaviour(Behaviour.GREETING, {}) is True
    assert step(ctl, backend) == []


def test_stale_token_is_ignored() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    old = ctl.begin_conversation()
    ctl.begin_conversation()
    ctl.run_pending()
    ctl.conversation_state(old, 1, LISTENING)
    ctl.end_conversation(old, completed=True)
    assert step(ctl, backend) == []
    assert ctl.conversation_owns_motion


def test_remote_control_excludes_conversation_motion() -> None:
    ctl, backend, state = make(conversation_motion=True, speech_wobble=True)
    state.remote_active = True
    token = ctl.begin_conversation()
    ctl.run_pending()
    ctl.conversation_state(token, 1, LISTENING)
    ctl.conversation_state(token, 1, SPEAKING)
    assert step(ctl, backend) == []
    ctl.end_conversation(token, completed=True)
    assert ("home",) not in step(ctl, backend)


def test_speech_wobble_follows_speaking() -> None:
    ctl, backend, _ = make(speech_wobble=True)
    token = ctl.begin_conversation()
    ctl.run_pending()
    ctl.conversation_state(token, 1, LISTENING)
    # Wobble alone plays no gestures.
    assert step(ctl, backend) == [("stop",)]
    ctl.conversation_state(token, 1, SPEAKING)
    assert step(ctl, backend) == [("stop",), ("wobble", True)]
    ctl.conversation_state(token, 2, LISTENING)
    assert step(ctl, backend) == [("wobble", False), ("stop",)]


def test_stop_disables_wobble_even_if_state_is_unknown() -> None:
    ctl, backend, _ = make(speech_wobble=True)
    ctl.stop()
    assert backend.calls == [("stop",), ("wobble", False)]


def test_stop_without_wobble_switch_leaves_wobble_alone() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    ctl.stop()
    assert backend.calls == [("stop",)]


def test_stop_invalidates_pending_transition_and_ends_ownership() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.conversation_state(token, 1, LISTENING)
    ctl.stop()
    assert step(ctl, backend) == []
    assert not ctl.conversation_owns_motion
    ctl.conversation_state(token, 1, THINKING)
    assert step(ctl, backend) == []


def test_stop_waits_for_in_flight_play_then_stops_it() -> None:
    ctl, backend, _ = make(conversation_motion=True, threaded=True)
    try:
        token = ctl.begin_conversation()
        backend.gate = threading.Event()
        ctl.conversation_state(token, 1, LISTENING)
        assert backend.entered.wait(5.0)
        stopper = threading.Thread(target=ctl.stop)
        stopper.start()
        stopper.join(0.2)
        assert stopper.is_alive()  # blocked behind the in-flight play
        backend.gate.set()
        stopper.join(5.0)
        assert not stopper.is_alive()
        assert backend.calls[-2:] == [LISTEN, ("stop",)]
    finally:
        if backend.gate is not None:
            backend.gate.set()
        ctl.close()


def test_worker_does_not_block_the_caller() -> None:
    ctl, backend, _ = make(conversation_motion=True, threaded=True)
    try:
        token = ctl.begin_conversation()
        backend.gate = threading.Event()
        ctl.conversation_state(token, 1, LISTENING)
        assert backend.entered.wait(5.0)
        # The caller returns while the daemon call is still blocked.
        ctl.conversation_state(token, 1, THINKING)
        ctl.conversation_state(token, 1, SPEAKING)
        backend.gate.set()
    finally:
        if backend.gate is not None:
            backend.gate.set()
        ctl.close()
    # Coalesced: THINKING was superseded by SPEAKING before it ran, then
    # close stopped everything.
    assert THINK not in backend.calls
    assert backend.calls[-1] == ("stop",)


def test_closed_controller_rejects_new_work() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    ctl.close()
    backend.calls.clear()
    assert ctl.request_behaviour(Behaviour.GREETING, {}) is False
    token = ctl.begin_conversation()
    ctl.conversation_state(token, 1, LISTENING)
    assert backend.calls == []


def test_runtime_settings_change_no_motion_and_wait_for_conversation_end():
    import pytest

    from shared.models.motion import MotionSettings

    ctl, backend, _ = make()
    enabled = MotionSettings(conversation_motion=True, speech_wobble=True)
    token = ctl.begin_conversation()  # Also protected when both flags are off.
    with pytest.raises(ValueError, match="Stop"):
        ctl.configure(enabled)
    ctl.end_conversation(token, completed=False)
    assert ctl.configure(enabled).conversation_motion
    assert backend.calls == []  # Saving is configuration, never a preview.
    token = ctl.begin_conversation()
    ctl.conversation_state(token, 1, SPEAKING)
    assert ("wobble", True) in step(ctl, backend)
    with pytest.raises(ValueError, match="Stop"):
        ctl.configure(MotionSettings(conversation_motion=False, speech_wobble=False))
    ctl.end_conversation(token, completed=False)
    with pytest.raises(ValueError, match="Stop"):
        ctl.configure(enabled)  # Stop is pending, so do not change flags yet.
    assert ("wobble", False) in step(ctl, backend)
    backend.calls.clear()
    ctl.configure(MotionSettings(conversation_motion=False, speech_wobble=False))
    token = ctl.begin_conversation()
    ctl.conversation_state(token, 2, LISTENING)
    ctl.run_pending()
    assert backend.calls == []


def test_presence_sweep_needs_its_switch_and_yields_to_conversation_and_remote_control() -> None:
    waits: list[float] = []
    off = MotionController(FakeBackend(), ServiceState(connected=True, sim=True), threaded=False)
    assert off.sweep_to(0) is False and off.sweep_home() is False

    backend = FakeBackend()
    backend.poses = []
    state = ServiceState(connected=True, sim=True)
    motion = MotionController(backend, state, presence_sweep=True, threaded=False, sleep=waits.append)
    assert motion.sweep_to(-1) is False and motion.sweep_to(5) is False and backend.poses == []
    assert motion.sweep_to(0) and motion.sweep_to(4)
    assert [p["body_yaw"] for p in backend.poses] == [-1.0, 1.0]
    assert [p["head_pose"]["yaw"] for p in backend.poses] == [-1.0, 1.0]
    assert all(p["head_pose"]["pitch"] == 0.0 and p["duration"] == 1.5 for p in backend.poses)
    assert motion.sweep_home() and backend.calls[-1] == ("home",) and waits == [2.0, 2.0, 1.2]

    state.remote_active = True
    assert motion.sweep_to(2) is False
    state.remote_active = False
    token = motion.begin_conversation()
    assert motion.sweep_to(2) is False
    motion.end_conversation(token, completed=False)
    motion.close()
    assert motion.sweep_to(2) is False
