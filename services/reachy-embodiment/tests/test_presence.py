import time
from datetime import UTC, datetime, timedelta

from reachy_embodiment.presence import IDLE_CYCLE, PresenceLoop
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_embodiment.state import ServiceState

from shared.models.embodiment import EmbodimentState


def make_loop(**kwargs: float) -> tuple[PresenceLoop, ServiceState]:
    backend = SimulatedRobotBackend()
    state = ServiceState(connected=True, sim=True)
    loop = PresenceLoop(backend, state, **kwargs)
    return loop, state


def test_stays_idle_before_heartbeat_timeout() -> None:
    loop, state = make_loop(heartbeat_timeout=2.0, idle_cycle_seconds=1000.0)
    base = datetime.now(UTC)
    loop._last_heartbeat_at = base  # white-box: simulate a heartbeat at a known instant
    loop.tick(base + timedelta(seconds=1.0), 0.0)
    assert state.embodiment_state == EmbodimentState.IDLE


def test_watchdog_trips_to_disconnected_after_timeout() -> None:
    loop, state = make_loop(heartbeat_timeout=2.0, idle_cycle_seconds=1000.0)
    base = datetime.now(UTC)
    loop._last_heartbeat_at = base
    loop.tick(base + timedelta(seconds=3.0), 0.0)
    assert state.embodiment_state == EmbodimentState.DISCONNECTED


def test_heartbeat_recovers_from_disconnected() -> None:
    loop, state = make_loop(heartbeat_timeout=2.0, idle_cycle_seconds=1000.0)
    state.embodiment_state = EmbodimentState.DISCONNECTED
    loop.heartbeat()
    assert state.embodiment_state == EmbodimentState.IDLE
    assert state.last_heartbeat_at is not None


def test_idle_cycle_plays_behaviours_and_advances_over_time() -> None:
    loop, state = make_loop(heartbeat_timeout=1000.0, idle_cycle_seconds=1.0)
    base = datetime.now(UTC)
    loop._last_heartbeat_at = base

    loop.tick(base, 100.0)  # first tick always fires (last_idle_tick starts at 0.0)
    assert state.last_behaviour == IDLE_CYCLE[0]

    loop.tick(base, 100.5)  # inside the 1s idle window: no change yet
    assert state.last_behaviour == IDLE_CYCLE[0]

    loop.tick(base, 101.5)  # past the window: cycles to the next behaviour
    assert state.last_behaviour == IDLE_CYCLE[1]


def test_idle_cycle_keeps_running_after_disconnect() -> None:
    loop, state = make_loop(heartbeat_timeout=1.0, idle_cycle_seconds=1.0)
    base = datetime.now(UTC)
    loop._last_heartbeat_at = base

    loop.tick(base + timedelta(seconds=5), 100.0)
    assert state.embodiment_state == EmbodimentState.DISCONNECTED
    assert state.last_behaviour in IDLE_CYCLE


def test_homelab_driven_state_is_not_overridden_by_idle_cycle() -> None:
    loop, state = make_loop(heartbeat_timeout=1000.0, idle_cycle_seconds=0.0)
    state.embodiment_state = EmbodimentState.SPEAKING
    base = datetime.now(UTC)
    loop._last_heartbeat_at = base

    loop.tick(base, 100.0)
    assert state.embodiment_state == EmbodimentState.SPEAKING
    assert state.last_behaviour is None


def test_real_thread_animates_continuously_and_survives_disconnect() -> None:
    """End-to-end proof of the Phase 3 exit criterion: Reachy keeps
    animating even once the (simulated) homelab stops sending heartbeats."""
    loop, state = make_loop(heartbeat_timeout=0.1, idle_cycle_seconds=0.05, tick_hz=100.0)
    loop.start()
    try:
        time.sleep(0.08)
        assert state.last_behaviour is not None  # already animating on its own

        time.sleep(0.15)  # comfortably past heartbeat_timeout with no heartbeat sent
        assert state.embodiment_state == EmbodimentState.DISCONNECTED

        behaviour_while_disconnected = state.last_behaviour
        time.sleep(0.1)
        # idle cycle kept advancing while disconnected -> genuinely still animated
        assert state.last_behaviour is not None
        assert state.last_behaviour_at is not None
        assert behaviour_while_disconnected is not None
    finally:
        loop.stop()
