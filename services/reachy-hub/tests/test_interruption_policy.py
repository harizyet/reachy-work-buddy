from datetime import UTC, datetime, timedelta

from reachy_hub.interruption_policy import (
    decide_action,
    downgrade_for_presence,
    is_occupied,
)

from shared.models.interruption import InterruptionAction
from shared.models.response import Urgency
from shared.models.session import PrivacyContext

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


# --- is_occupied ---


def test_not_occupied_by_default() -> None:
    assert is_occupied(dnd=False, privacy_context=PrivacyContext.UNKNOWN, event_in_progress=False) is False


def test_dnd_alone_is_occupied() -> None:
    assert is_occupied(dnd=True, privacy_context=PrivacyContext.UNKNOWN, event_in_progress=False) is True


def test_meeting_privacy_context_is_occupied() -> None:
    assert is_occupied(dnd=False, privacy_context=PrivacyContext.MEETING, event_in_progress=False) is True


def test_calendar_event_in_progress_is_occupied_even_without_dnd_or_manual_meeting() -> None:
    assert is_occupied(dnd=False, privacy_context=PrivacyContext.UNKNOWN, event_in_progress=True) is True


# --- decide_action: occupied branch ---


def test_occupied_low_urgency_is_ignored() -> None:
    assert (
        decide_action(occupied=True, urgency=Urgency.LOW, last_interruption_at=None, now=NOW)
        is InterruptionAction.IGNORE
    )


def test_occupied_normal_urgency_is_queued() -> None:
    assert (
        decide_action(occupied=True, urgency=Urgency.NORMAL, last_interruption_at=None, now=NOW)
        is InterruptionAction.QUEUE
    )


def test_occupied_urgent_is_gesture() -> None:
    assert (
        decide_action(occupied=True, urgency=Urgency.URGENT, last_interruption_at=None, now=NOW)
        is InterruptionAction.GESTURE
    )


# --- decide_action: free branch ---


def test_free_low_urgency_is_text() -> None:
    assert (
        decide_action(occupied=False, urgency=Urgency.LOW, last_interruption_at=None, now=NOW)
        is InterruptionAction.TEXT
    )


def test_free_normal_urgency_not_recently_interrupted_is_interrupt() -> None:
    assert (
        decide_action(occupied=False, urgency=Urgency.NORMAL, last_interruption_at=None, now=NOW)
        is InterruptionAction.INTERRUPT
    )


def test_free_urgent_is_always_interrupt_regardless_of_cooldown() -> None:
    recent = NOW - timedelta(seconds=5)
    assert (
        decide_action(occupied=False, urgency=Urgency.URGENT, last_interruption_at=recent, now=NOW)
        is InterruptionAction.INTERRUPT
    )


def test_free_normal_urgency_recently_interrupted_downgrades_to_text() -> None:
    recent = NOW - timedelta(seconds=5)
    assert (
        decide_action(
            occupied=False, urgency=Urgency.NORMAL, last_interruption_at=recent, now=NOW, cooldown_seconds=120
        )
        is InterruptionAction.TEXT
    )


def test_free_normal_urgency_outside_cooldown_is_interrupt() -> None:
    stale = NOW - timedelta(seconds=200)
    assert (
        decide_action(
            occupied=False, urgency=Urgency.NORMAL, last_interruption_at=stale, now=NOW, cooldown_seconds=120
        )
        is InterruptionAction.INTERRUPT
    )


# --- downgrade_for_presence ---


def test_gesture_downgrades_to_text_when_no_robot_available() -> None:
    assert (
        downgrade_for_presence(InterruptionAction.GESTURE, robot_available=False) is InterruptionAction.TEXT
    )


def test_gesture_stays_gesture_when_robot_available() -> None:
    assert (
        downgrade_for_presence(InterruptionAction.GESTURE, robot_available=True) is InterruptionAction.GESTURE
    )


def test_downgrade_only_affects_gesture() -> None:
    for action in (InterruptionAction.IGNORE, InterruptionAction.QUEUE, InterruptionAction.TEXT, InterruptionAction.INTERRUPT):
        assert downgrade_for_presence(action, robot_available=False) is action
