"""Deterministic interruption decision-making. See
docs/adr/0014-interruption-intelligence.md.

A third pure policy function alongside response_policy.py's two:
resolve_delivery_channel/apply_privacy_override decide *where* a proactive
notification goes; is_occupied/decide_action/downgrade_for_presence decide
*whether and how aggressively* to deliver it right now. Neither reads the
other's inputs — composed by the impure handler in app.py, same pattern
ADR 0006 established.

This engine gates proactive notifications only (today: calendar
reminders). It is never consulted for a direct reply to a direct message
(/messages, /voice/turn) — ADR 0006's addendum is explicit that
delivery_channel "does not gate a direct reply to a direct message", and
the same reasoning applies to whether/when, not just where.
"""

from __future__ import annotations

from datetime import datetime

from shared.models.interruption import InterruptionAction
from shared.models.response import Urgency
from shared.models.session import PrivacyContext


def is_occupied(*, dnd: bool, privacy_context: PrivacyContext, event_in_progress: bool) -> bool:
    return dnd or privacy_context == PrivacyContext.MEETING or event_in_progress


def decide_action(
    *,
    occupied: bool,
    urgency: Urgency,
    last_interruption_at: datetime | None,
    now: datetime,
    cooldown_seconds: float = 120.0,
) -> InterruptionAction:
    if occupied:
        # docs §4: "Active meeting/DND -> queue or silent notification",
        # "Urgent event -> phone alert plus Reachy attention gesture" — the
        # urgent carve-out from the first rule. Routine (LOW) notifications
        # aren't even worth queueing for later replay once the user is
        # free again; only NORMAL is.
        if urgency is Urgency.URGENT:
            return InterruptionAction.GESTURE
        if urgency is Urgency.LOW:
            return InterruptionAction.IGNORE
        return InterruptionAction.QUEUE

    recently_interrupted = (
        last_interruption_at is not None and (now - last_interruption_at).total_seconds() < cooldown_seconds
    )
    if urgency is Urgency.LOW or (urgency is Urgency.NORMAL and recently_interrupted):
        return InterruptionAction.TEXT
    return InterruptionAction.INTERRUPT


def downgrade_for_presence(action: InterruptionAction, *, robot_available: bool) -> InterruptionAction:
    """GESTURE is the only action that fundamentally needs a reachable
    robot — QUEUE/TEXT/INTERRUPT's actual delivery already goes over
    Telegram/phone, never through the robot itself, in this codebase."""
    if action is InterruptionAction.GESTURE and not robot_available:
        return InterruptionAction.TEXT
    return action
