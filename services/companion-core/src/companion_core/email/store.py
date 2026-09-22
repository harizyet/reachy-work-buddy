"""Email storage: received messages (seeded, see models.py) and drafts
with an approval-gated, delay-queued status. queue_draft/cancel_queued_draft
only flip status flags — they do not send anything; only
email/workflow.py's dispatch_due_drafts ever calls an EmailSender, and
only after checking QUEUED status and dispatch_at. Single mailbox, not
scoped per user — same precedent as calendar/tasks (this is a personal
assistant, not multi-tenant).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from companion_core.email.models import DraftStatus, EmailDraft, EmailMessage


class EmailStore(Protocol):
    async def add_received(self, *, sender: str, subject: str, body: str) -> EmailMessage: ...

    async def list_received(self) -> list[EmailMessage]: ...

    async def create_draft(
        self, *, to: str, subject: str, body: str, in_reply_to: str | None = None
    ) -> EmailDraft: ...

    async def list_drafts(self, status: DraftStatus | None = None) -> list[EmailDraft]: ...

    async def get_draft(self, draft_id: str) -> EmailDraft | None: ...

    async def approve_draft(self, draft_id: str) -> EmailDraft | None: ...

    async def queue_draft(self, draft_id: str, *, dispatch_at: datetime) -> EmailDraft | None: ...

    async def cancel_queued_draft(self, draft_id: str) -> EmailDraft | None: ...

    async def list_due(self, now: datetime) -> list[EmailDraft]: ...

    async def mark_sent(self, draft_id: str) -> EmailDraft | None: ...


class InMemoryEmailStore:
    def __init__(self) -> None:
        self._received: dict[str, EmailMessage] = {}
        self._drafts: dict[str, EmailDraft] = {}

    async def add_received(self, *, sender: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage(sender=sender, subject=subject, body=body)
        self._received[message.id] = message
        return message

    async def list_received(self) -> list[EmailMessage]:
        return sorted(self._received.values(), key=lambda m: m.received_at)

    async def create_draft(
        self, *, to: str, subject: str, body: str, in_reply_to: str | None = None
    ) -> EmailDraft:
        draft = EmailDraft(to=to, subject=subject, body=body, in_reply_to=in_reply_to)
        self._drafts[draft.id] = draft
        return draft

    async def list_drafts(self, status: DraftStatus | None = None) -> list[EmailDraft]:
        drafts = list(self._drafts.values())
        if status is not None:
            drafts = [d for d in drafts if d.status == status]
        return sorted(drafts, key=lambda d: d.created_at)

    async def get_draft(self, draft_id: str) -> EmailDraft | None:
        return self._drafts.get(draft_id)

    async def approve_draft(self, draft_id: str) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status != DraftStatus.DRAFT:
            return None
        draft.status = DraftStatus.APPROVED
        draft.approved_at = datetime.now(UTC)
        return draft

    async def queue_draft(self, draft_id: str, *, dispatch_at: datetime) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status != DraftStatus.APPROVED:
            return None
        draft.status = DraftStatus.QUEUED
        draft.dispatch_at = dispatch_at
        return draft

    async def cancel_queued_draft(self, draft_id: str) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status != DraftStatus.QUEUED:
            return None
        draft.status = DraftStatus.APPROVED
        draft.dispatch_at = None
        return draft

    async def list_due(self, now: datetime) -> list[EmailDraft]:
        return [
            d
            for d in self._drafts.values()
            if d.status == DraftStatus.QUEUED and d.dispatch_at is not None and d.dispatch_at <= now
        ]

    async def mark_sent(self, draft_id: str) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None:
            return None
        draft.status = DraftStatus.SENT
        draft.sent_at = datetime.now(UTC)
        return draft
