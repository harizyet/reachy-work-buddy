"""The approval gate. `send_approved_draft` is the *only* function
anywhere in this codebase that calls a `SendFn` — both the direct API
(`POST /emails/drafts/{id}/send`) and the conversational "send draft X"
path in app.py call this and nothing else, never a sender directly. That's
what makes Phase 14's exit criterion ("No code path sends mail without
approval gate") a structural property of the code, not just a claim about
it: there is exactly one call site for dispatch, and it's gated.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from companion_core.email.models import DraftStatus, EmailDraft
from companion_core.email.sender import smtp_send
from companion_core.email.store import EmailStore

SendFn = Callable[[EmailDraft], Awaitable[None]]


class DraftNotApprovedError(Exception):
    def __init__(self, draft_id: str, status: DraftStatus) -> None:
        self.draft_id = draft_id
        self.status = status
        super().__init__(f"draft '{draft_id}' is not approved (status: {status})")


async def send_approved_draft(store: EmailStore, draft_id: str, *, send_fn: SendFn = smtp_send) -> EmailDraft:
    draft = await store.get_draft(draft_id)
    if draft is None:
        raise LookupError(f"no draft '{draft_id}'")
    if draft.status != DraftStatus.APPROVED:
        raise DraftNotApprovedError(draft_id, draft.status)
    await send_fn(draft)
    sent = await store.mark_sent(draft_id)
    assert sent is not None  # get_draft above already confirmed it exists
    return sent
