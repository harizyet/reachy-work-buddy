"""The two hard rules, enforced structurally rather than as a claim (see
docs/adr/0011): a destructive action can never be requested at BULK scope
— `request_confirmation` raises before a row is even created, so there is
no confirmation to approve, textually or otherwise — and a confirmation
can never be accepted from voice input — `confirm_action` raises before
touching the store. Every destructive code path in this codebase (memory
forget, email send) must call these two functions rather than talking to
a ConfirmationStore directly; a future Gmail/Outlook/calendar-delete
connector must do the same (see the ADR) for this guarantee to keep
holding.
"""

from __future__ import annotations

from companion_core.consent.models import ActionScope, ConfirmationRequest
from companion_core.consent.store import ConfirmationStore
from shared.models.session import InputModality

DEFAULT_TTL_SECONDS = 300  # 5 minutes — deliberately short: a stale, long-
# forgotten pending deletion sitting around is itself a risk.


class BulkActionBlockedError(Exception):
    """Raised by request_confirmation for ActionScope.BULK — always, no
    override. Mass-destructive actions ("delete all memories", "empty the
    mailbox") have no path to confirmation in this codebase at all."""

    def __init__(self, action_type: str) -> None:
        self.action_type = action_type
        super().__init__(f"bulk-scoped action '{action_type}' is unconditionally blocked, no confirmation possible")


class VoiceConfirmationNotAllowedError(Exception):
    """Raised whenever a destructive-action confirmation is attempted from
    InputModality.VOICE. Voice is ambient, unauthenticated, easy to mishear
    or spoof — this codebase's one hard rule is that it can never authorize
    anything destructive, regardless of what it transcribes to."""


class ConfirmationNotFoundError(Exception):
    pass


class ConfirmationExpiredError(Exception):
    pass


async def request_confirmation(
    store: ConfirmationStore,
    *,
    action_type: str,
    target_id: str,
    description: str,
    scope: ActionScope = ActionScope.SINGLE,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> ConfirmationRequest:
    if scope == ActionScope.BULK:
        raise BulkActionBlockedError(action_type)
    return await store.create(
        action_type=action_type, target_id=target_id, description=description, scope=scope, ttl_seconds=ttl_seconds
    )


def require_text(input_modality: InputModality) -> None:
    """Standalone version of the voice check, for destructive/consequential
    flows that don't go through the ID-based ConfirmationStore (e.g.
    email's approve/send, which already has its own natural two-step
    confirmation UX) but still must never accept voice as consent."""
    if input_modality == InputModality.VOICE:
        raise VoiceConfirmationNotAllowedError


async def confirm_action(
    store: ConfirmationStore, confirmation_id: str, *, input_modality: InputModality
) -> ConfirmationRequest:
    require_text(input_modality)
    request = await store.get(confirmation_id)
    if request is None:
        raise ConfirmationNotFoundError(confirmation_id)
    confirmed = await store.confirm(confirmation_id)
    if confirmed is None:
        raise ConfirmationExpiredError(confirmation_id)
    return confirmed
