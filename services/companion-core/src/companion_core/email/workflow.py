"""The send pipeline (docs/adr/0011): "send draft X" only *queues* a
dispatch ~10 minutes out — `queue_draft_for_sending` — giving the user a
window to cancel (`cancel_queued_draft`) before anything actually goes
out. `dispatch_due_drafts` is the *only* function anywhere in this
codebase that calls a `SendFn` — it's what a background loop
(`run_dispatch_loop`) calls on an interval, checking `EmailStore.list_due`
for QUEUED drafts whose `dispatch_at` has passed. Both the direct API and
the conversational path only ever reach a real send through this one
function; nothing calls a SendFn directly. Same "unit test the step
function with controlled time, one real background-task test with a short
interval" split AGENTS.md documents for the presence/heartbeat loops.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from companion_core.email.models import DraftStatus, EmailDraft
from companion_core.email.sender import smtp_send
from companion_core.email.store import EmailStore

SendFn = Callable[[EmailDraft], Awaitable[None]]

DEFAULT_SEND_DELAY_SECONDS = 600  # 10 minutes — the "changed your mind" window.

log = logging.getLogger(__name__)


class DraftNotApprovedError(Exception):
    def __init__(self, draft_id: str, status: DraftStatus) -> None:
        self.draft_id = draft_id
        self.status = status
        super().__init__(f"draft '{draft_id}' is not approved (status: {status})")


class DraftNotQueuedError(Exception):
    def __init__(self, draft_id: str, status: DraftStatus) -> None:
        self.draft_id = draft_id
        self.status = status
        super().__init__(f"draft '{draft_id}' is not queued for sending (status: {status})")


async def queue_draft_for_sending(
    store: EmailStore, draft_id: str, *, delay_seconds: int = DEFAULT_SEND_DELAY_SECONDS
) -> EmailDraft:
    """Moves an APPROVED draft to QUEUED with dispatch_at = now + delay.
    Does not send anything — dispatch_due_drafts does that, later, only
    once dispatch_at has passed."""
    draft = await store.get_draft(draft_id)
    if draft is None:
        raise LookupError(f"no draft '{draft_id}'")
    if draft.status != DraftStatus.APPROVED:
        raise DraftNotApprovedError(draft_id, draft.status)
    dispatch_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    queued = await store.queue_draft(draft_id, dispatch_at=dispatch_at)
    assert queued is not None  # get_draft above already confirmed APPROVED
    return queued


async def cancel_queued_draft(store: EmailStore, draft_id: str) -> EmailDraft:
    """The undo: reverts QUEUED back to APPROVED, clearing dispatch_at.
    Always allowed regardless of channel/modality — undoing is the safe
    direction and must never be harder than the action it undoes."""
    draft = await store.get_draft(draft_id)
    if draft is None:
        raise LookupError(f"no draft '{draft_id}'")
    if draft.status != DraftStatus.QUEUED:
        raise DraftNotQueuedError(draft_id, draft.status)
    cancelled = await store.cancel_queued_draft(draft_id)
    assert cancelled is not None
    return cancelled


async def dispatch_due_drafts(store: EmailStore, *, send_fn: SendFn = smtp_send, now: datetime | None = None) -> int:
    """The step function: sends every QUEUED draft whose dispatch_at has
    passed, and only those. Returns how many were dispatched. `now` is
    injectable so this can be unit-tested with controlled time instead of
    real sleeps."""
    due = await store.list_due(now or datetime.now(UTC))
    for draft in due:
        await send_fn(draft)
        await store.mark_sent(draft.id)
    return len(due)


async def run_dispatch_loop(store: EmailStore, *, send_fn: SendFn = smtp_send, interval_seconds: float = 30) -> None:
    """Real background task — started from create_app's lifespan, same
    pattern as reachy-hub's heartbeat loop. Errors from one dispatch pass
    are logged and swallowed, not left to kill the loop; a transient SMTP
    failure shouldn't silently stop all future sends from ever being
    retried on the next pass."""
    while True:
        try:
            await dispatch_due_drafts(store, send_fn=send_fn)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("email dispatch loop: error processing due drafts")
        await asyncio.sleep(interval_seconds)
