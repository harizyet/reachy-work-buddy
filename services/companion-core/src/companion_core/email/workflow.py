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
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from companion_core.email.models import DraftStatus, EmailDraft, package_hash
from companion_core.email.sender import (
    SendRefused,
    SendTransient,
    SendUnknown,
    smtp_send,
)
from companion_core.email.store import EmailStore

# A sender returns the server's acceptance line (or None) and raises SendRefused / SendTransient / SendUnknown (email/sender.py) so the loop knows what a failure means.
SendFn = Callable[[EmailDraft], Awaitable[str | None]]

MAX_ATTEMPTS = 3  # transient failures only: a refusal or an ambiguous outcome is never retried by the loop
RETRY_DELAYS_SECONDS = (60, 300)
STUCK_AFTER_SECONDS = 300  # longer than the SMTP timeout: a message still SENDING after this belongs to a process that is gone

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


async def _integrity_error(store: EmailStore, draft: EmailDraft, blobs: list) -> str | None:
    """What was approved must be what is sent. A package (it has a hash) is re-verified from the stored rows: nothing is regenerated and nothing is trusted from memory."""
    if draft.package_hash is None:
        return None
    if package_hash(draft, draft.sender) != draft.approved_hash or draft.package_hash != draft.approved_hash:
        return "the message changed after it was approved"
    stored = {a.name: a for a in draft.attachments}
    if {n for n, _c, _d in blobs} != set(stored) or any(hashlib.sha256(d).hexdigest() != stored[n].sha256 for n, _c, d in blobs):
        return "an attachment does not match what was approved"
    return None


async def _deliver(store: EmailStore, draft: EmailDraft, send_fn: SendFn, now: datetime) -> bool:
    blobs = await store.get_blobs(draft.id)
    problem = await _integrity_error(store, draft, blobs)
    if problem:
        await store.mark_failed(draft.id, error=problem)
        await store.add_event(draft.id, "failed", {"reason": problem, "attempt": draft.attempts})
        return False
    await store.add_event(draft.id, "sending", {"attempt": draft.attempts, "sender": draft.sender})
    try:
        response = await send_fn(draft.model_copy(update={"attachment_blobs": blobs}))
    except SendRefused as exc:
        await store.mark_failed(draft.id, error=str(exc))
        await store.add_event(draft.id, "failed", {"reason": str(exc), "attempt": draft.attempts})
        return False
    except SendTransient as exc:
        if draft.attempts < MAX_ATTEMPTS:
            delay = RETRY_DELAYS_SECONDS[min(draft.attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)]
            await store.requeue_for_retry(draft.id, dispatch_at=now + timedelta(seconds=delay), error=str(exc))
            await store.add_event(draft.id, "retry_scheduled", {"reason": str(exc), "attempt": draft.attempts, "in_seconds": delay})
        else:
            await store.mark_failed(draft.id, error=f"{exc} (gave up after {draft.attempts} attempts)")
            await store.add_event(draft.id, "failed", {"reason": str(exc), "attempt": draft.attempts})
        return False
    except SendUnknown as exc:
        await store.mark_unknown(draft.id, error=str(exc))
        await store.add_event(draft.id, "unknown_delivery", {"reason": str(exc), "attempt": draft.attempts})
        return False
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("email dispatch: unexpected error sending %s", draft.id)
        await store.mark_unknown(draft.id, error=f"unexpected {type(exc).__name__}")
        await store.add_event(draft.id, "unknown_delivery", {"reason": f"unexpected {type(exc).__name__}", "attempt": draft.attempts})
        return False
    await store.mark_sent(draft.id, provider_response=response)
    await store.add_event(draft.id, "sent", {"attempt": draft.attempts, "provider_response": response})
    return True


async def recover_interrupted(store: EmailStore, *, now: datetime | None = None, older_than_seconds: float | None = STUCK_AFTER_SECONDS) -> int:
    """A draft left SENDING by a process that stopped may or may not have been delivered: it becomes UNKNOWN_DELIVERY (never retried automatically) for the owner to reconcile."""
    cutoff = None if older_than_seconds is None else (now or datetime.now(UTC)) - timedelta(seconds=older_than_seconds)  # None: every SENDING row, whatever its age
    stuck = await store.recover_stuck(cutoff)
    for draft in stuck:
        await store.add_event(draft.id, "unknown_delivery", {"reason": "interrupted while sending"})
    return len(stuck)


async def dispatch_due_drafts(store: EmailStore, *, send_fn: SendFn = smtp_send, now: datetime | None = None) -> int:
    """The step function: claims each QUEUED draft whose dispatch_at has passed (atomically, one at a time) and sends it, and only those. Returns how many were delivered. `now` is
    injectable so this can be unit-tested with controlled time instead of real sleeps. The send function sees the stored, hash-verified package: nothing is regenerated here."""
    moment = now or datetime.now(UTC)
    sent = 0
    while (draft := await store.claim_due(moment)) is not None:
        if await _deliver(store, draft, send_fn, moment):
            sent += 1
    return sent


async def run_dispatch_loop(store: EmailStore, *, send_fn: SendFn = smtp_send, interval_seconds: float = 30) -> None:
    """Real background task — started from create_app's lifespan, same
    pattern as reachy-hub's heartbeat loop. Errors from one dispatch pass
    are logged and swallowed, not left to kill the loop. On start, anything
    still SENDING belongs to a process that no longer exists and is settled
    as UNKNOWN_DELIVERY before the first pass."""
    try:
        await recover_interrupted(store, older_than_seconds=None)  # every SENDING row: we have just started, so none is ours
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("email dispatch loop: could not recover interrupted sends")
    while True:
        try:
            await recover_interrupted(store)
            await dispatch_due_drafts(store, send_fn=send_fn)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("email dispatch loop: error processing due drafts")
        await asyncio.sleep(interval_seconds)
