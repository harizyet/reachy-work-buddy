import threading

from reachy_embodiment.motion import MotionController
from reachy_embodiment.state import ServiceState

from shared.models.embodiment import Behaviour, EmbodimentState

LISTENING = EmbodimentState.LISTENING
THINKING = EmbodimentState.THINKING
SPEAKING = EmbodimentState.SPEAKING


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    def play_behaviour(self, name: Behaviour, parameters: dict[str, str]) -> None:
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5.0)
        self.calls.append(("play", name))

    def stop_motion(self) -> None:
        self.calls.append(("stop",))

    def goto_home(self) -> None:
        self.calls.append(("home",))

    def set_speech_wobble(self, enabled: bool) -> None:
        self.calls.append(("wobble", enabled))


def make(**kwargs) -> tuple[MotionController, FakeBackend, ServiceState]:
    backend = FakeBackend()
    state = ServiceState()
    kwargs.setdefault("threaded", False)
    kwargs.setdefault("home_settle_seconds", 0.0)
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


def test_gestures_once_per_turn_and_state() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    token = ctl.begin_conversation()
    ctl.run_pending()

    ctl.conversation_state(token, 1, LISTENING)
    assert step(ctl, backend) == [("play", Behaviour.LISTENING)]
    # A gesture leaves the head at its own end pose, so the next one
    # starts from home rather than jumping to its first frame.
    ctl.conversation_state(token, 1, THINKING)
    assert step(ctl, backend) == [("home",), ("play", Behaviour.THINKING)]
    # Held segment: back to listening in the same turn returns home
    # without replaying the listening gesture.
    ctl.conversation_state(token, 1, LISTENING)
    assert step(ctl, backend) == [("home",)]
    ctl.conversation_state(token, 1, THINKING)
    assert step(ctl, backend) == [("stop",)]  # already home
    ctl.conversation_state(token, 1, SPEAKING)
    assert step(ctl, backend) == [("stop",)]
    ctl.conversation_state(token, 2, LISTENING)
    assert step(ctl, backend) == [("play", Behaviour.LISTENING)]


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


def test_stop_during_the_return_home_cancels_the_next_gesture() -> None:
    backend = FakeBackend()
    ctl = MotionController(
        backend, ServiceState(), conversation_motion=True, threaded=True, home_settle_seconds=5.0
    )
    try:
        token = ctl.begin_conversation()
        ctl.conversation_state(token, 1, LISTENING)
        deadline = threading.Event()
        while ("play", Behaviour.LISTENING) not in backend.calls and not deadline.wait(0.01):
            pass
        ctl.conversation_state(token, 1, THINKING)  # worker goes home, then waits
        while backend.calls.count(("home",)) < 1 and not deadline.wait(0.01):
            pass
        stopper = threading.Thread(target=ctl.stop)
        stopper.start()
        stopper.join(2.0)
        assert not stopper.is_alive()  # the wait ended at once, not after 5 s
        assert ("play", Behaviour.THINKING) not in backend.calls
        assert backend.calls[-1] == ("stop",)
    finally:
        ctl.close()


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
    assert step(ctl, backend) == [("play", Behaviour.THINKING)]


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
        assert backend.calls[-2:] == [("play", Behaviour.LISTENING), ("stop",)]
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
    assert ("play", Behaviour.THINKING) not in backend.calls
    assert backend.calls[-1] == ("stop",)


def test_closed_controller_rejects_new_work() -> None:
    ctl, backend, _ = make(conversation_motion=True)
    ctl.close()
    backend.calls.clear()
    assert ctl.request_behaviour(Behaviour.GREETING, {}) is False
    token = ctl.begin_conversation()
    ctl.conversation_state(token, 1, LISTENING)
    assert backend.calls == []
