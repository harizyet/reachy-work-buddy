from __future__ import annotations

from enum import StrEnum


class InterruptionAction(StrEnum):
    """See docs/adr/0014-interruption-intelligence.md.

    Decided by reachy-hub's interruption_policy.py for proactive
    notifications only (calendar reminders today) — never for a direct
    reply to a direct message (see ADR 0006's addendum).
    """

    IGNORE = "ignore"
    QUEUE = "queue"
    TEXT = "text"
    GESTURE = "gesture"
    INTERRUPT = "interrupt"
