"""Email storage: received messages (seeded, see models.py) and drafts
with an approval-gated, delay-queued status. queue_draft/cancel_queued_draft
only flip status flags — they do not send anything; only
email/workflow.py's dispatch_due_drafts ever calls an EmailSender, and
only after claiming a QUEUED draft whose dispatch_at has passed. Single
mailbox, not scoped per user — same precedent as calendar/tasks (this is a
personal assistant, not multi-tenant).

Phase 55 adds structured drafts (a meeting-minutes package: several recipients,
attachments, a package hash the owner's approval is bound to), an atomic
claim for dispatch, outcome recording (sent / failed / unknown delivery) and a
per-draft event history. Everything is additive: a text draft behaves as before.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from companion_core.email.models import (
    AttachmentMeta,
    DraftStatus,
    EmailDraft,
    EmailEvent,
    EmailMessage,
    Recipients,
    package_hash,
)

Blob = tuple[str, str, bytes]  # (file name, content type, bytes)
EDITABLE = (DraftStatus.DRAFT, DraftStatus.READY_FOR_REVIEW, DraftStatus.APPROVED)


class EmailStore(Protocol):
    async def add_received(self, *, sender: str, subject: str, body: str) -> EmailMessage: ...

    async def list_received(self) -> list[EmailMessage]: ...

    async def create_draft(
        self, *, to: str, subject: str, body: str, in_reply_to: str | None = None
    ) -> EmailDraft: ...

    async def create_package(self, draft: EmailDraft, blobs: list[Blob]) -> EmailDraft: ...

    async def list_drafts(self, status: DraftStatus | None = None, *, kind: str | None = None) -> list[EmailDraft]: ...

    async def get_draft(self, draft_id: str) -> EmailDraft | None: ...

    async def get_blobs(self, draft_id: str) -> list[Blob]: ...

    async def update_package(
        self, draft_id: str, *, recipients: Recipients, subject: str, body: str, sender: str, blobs: list[Blob] | None = None, source: dict | None = None
    ) -> EmailDraft | None: ...

    async def approve_draft(self, draft_id: str) -> EmailDraft | None: ...

    async def approve_reviewed(self, draft_id: str, *, package_hash: str, message_id: str) -> EmailDraft | None: ...

    async def queue_draft(self, draft_id: str, *, dispatch_at: datetime) -> EmailDraft | None: ...

    async def cancel_queued_draft(self, draft_id: str) -> EmailDraft | None: ...

    async def discard_draft(self, draft_id: str) -> EmailDraft | None: ...

    async def list_due(self, now: datetime) -> list[EmailDraft]: ...

    async def claim_due(self, now: datetime) -> EmailDraft | None: ...

    async def mark_sent(self, draft_id: str, *, provider_response: str | None = None) -> EmailDraft | None: ...

    async def mark_failed(self, draft_id: str, *, error: str) -> EmailDraft | None: ...

    async def mark_unknown(self, draft_id: str, *, error: str) -> EmailDraft | None: ...

    async def requeue_for_retry(self, draft_id: str, *, dispatch_at: datetime, error: str) -> EmailDraft | None: ...

    async def recover_stuck(self, older_than: datetime | None) -> list[EmailDraft]: ...

    async def resolve_unknown(self, draft_id: str, *, delivered: bool) -> EmailDraft | None: ...

    async def add_event(self, draft_id: str, event: str, detail: dict | None = None) -> None: ...

    async def list_events(self, draft_id: str) -> list[EmailEvent]: ...


def _meta(blobs: list[Blob]) -> list[AttachmentMeta]:
    import hashlib

    return [AttachmentMeta(name=n, content_type=c, sha256=hashlib.sha256(d).hexdigest(), size=len(d)) for n, c, d in blobs]


class InMemoryEmailStore:
    def __init__(self) -> None:
        self._received: dict[str, EmailMessage] = {}
        self._drafts: dict[str, EmailDraft] = {}
        self._blobs: dict[str, list[Blob]] = {}
        self._events: list[EmailEvent] = []

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

    async def create_package(self, draft: EmailDraft, blobs: list[Blob]) -> EmailDraft:
        draft = draft.model_copy(update={"attachments": _meta(blobs), "attachment_blobs": []})
        draft.package_hash = package_hash(draft, draft.sender)
        self._drafts[draft.id] = draft
        self._blobs[draft.id] = list(blobs)
        return draft

    async def list_drafts(self, status: DraftStatus | None = None, *, kind: str | None = None) -> list[EmailDraft]:
        drafts = list(self._drafts.values())
        if status is not None:
            drafts = [d for d in drafts if d.status == status]
        if kind is not None:
            drafts = [d for d in drafts if d.kind == kind]
        return sorted(drafts, key=lambda d: d.created_at)

    async def get_draft(self, draft_id: str) -> EmailDraft | None:
        return self._drafts.get(draft_id)

    async def get_blobs(self, draft_id: str) -> list[Blob]:
        return list(self._blobs.get(draft_id, []))

    async def update_package(self, draft_id, *, recipients, subject, body, sender, blobs=None, source=None):
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status not in EDITABLE:
            return None
        if blobs is not None:
            self._blobs[draft_id] = list(blobs)
            draft.attachments = _meta(blobs)
        draft.recipients, draft.subject, draft.body, draft.sender = recipients, subject, body, sender
        if source is not None:
            draft.source = source
        draft.to = recipients.to[0] if recipients.to else draft.to
        draft.package_hash = package_hash(draft, sender)
        # Any change returns the package to review: an earlier approval covered different content.
        draft.status, draft.approved_hash, draft.approved_at, draft.dispatch_at = DraftStatus.READY_FOR_REVIEW, None, None, None
        return draft

    async def approve_draft(self, draft_id: str) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status != DraftStatus.DRAFT or draft.kind != "text":
            return None
        draft.status = DraftStatus.APPROVED
        draft.approved_at = datetime.now(UTC)
        return draft

    async def approve_reviewed(self, draft_id: str, *, package_hash: str, message_id: str) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status != DraftStatus.READY_FOR_REVIEW or draft.package_hash != package_hash:
            return None
        draft.status, draft.approved_hash, draft.approved_at, draft.message_id = DraftStatus.APPROVED, package_hash, datetime.now(UTC), message_id
        return draft

    async def queue_draft(self, draft_id: str, *, dispatch_at: datetime) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status != DraftStatus.APPROVED or draft.approved_hash != draft.package_hash:
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

    async def discard_draft(self, draft_id: str) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status not in (*EDITABLE, DraftStatus.QUEUED, DraftStatus.FAILED, DraftStatus.UNKNOWN_DELIVERY):
            return None
        draft.status, draft.dispatch_at = DraftStatus.CANCELLED, None
        return draft

    async def list_due(self, now: datetime) -> list[EmailDraft]:
        return [
            d
            for d in self._drafts.values()
            if d.status == DraftStatus.QUEUED and d.dispatch_at is not None and d.dispatch_at <= now
        ]

    async def claim_due(self, now: datetime) -> EmailDraft | None:
        for draft in sorted(await self.list_due(now), key=lambda d: d.dispatch_at):
            if draft.approved_hash != draft.package_hash:
                continue
            draft.status, draft.claimed_at, draft.attempts = DraftStatus.SENDING, now, draft.attempts + 1
            return draft.model_copy()
        return None

    def _settle(self, draft_id: str, status: DraftStatus, **fields) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status != DraftStatus.SENDING:
            return None
        for key, value in fields.items():
            setattr(draft, key, value)
        draft.status, draft.claimed_at = status, None
        return draft

    async def mark_sent(self, draft_id: str, *, provider_response: str | None = None) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None:
            return None
        if draft.status == DraftStatus.SENDING:
            return self._settle(draft_id, DraftStatus.SENT, sent_at=datetime.now(UTC), provider_response=provider_response, last_error=None)
        if draft.status in (DraftStatus.QUEUED, DraftStatus.UNKNOWN_DELIVERY):  # a plain queued draft (older call sites) or the owner's own reconciliation
            draft.status, draft.sent_at, draft.provider_response = DraftStatus.SENT, datetime.now(UTC), provider_response
            return draft
        return None

    async def mark_failed(self, draft_id: str, *, error: str) -> EmailDraft | None:
        return self._settle(draft_id, DraftStatus.FAILED, last_error=error)

    async def mark_unknown(self, draft_id: str, *, error: str) -> EmailDraft | None:
        return self._settle(draft_id, DraftStatus.UNKNOWN_DELIVERY, last_error=error)

    async def requeue_for_retry(self, draft_id: str, *, dispatch_at: datetime, error: str) -> EmailDraft | None:
        return self._settle(draft_id, DraftStatus.QUEUED, dispatch_at=dispatch_at, last_error=error)

    async def recover_stuck(self, older_than: datetime | None) -> list[EmailDraft]:
        stuck = [d for d in self._drafts.values() if d.status == DraftStatus.SENDING and (older_than is None or (d.claimed_at is not None and d.claimed_at < older_than))]
        return [self._settle(d.id, DraftStatus.UNKNOWN_DELIVERY, last_error="the process stopped while this message was being sent; it may or may not have been delivered") for d in stuck]

    async def resolve_unknown(self, draft_id: str, *, delivered: bool) -> EmailDraft | None:
        draft = self._drafts.get(draft_id)
        if draft is None or draft.status != DraftStatus.UNKNOWN_DELIVERY:
            return None
        if delivered:
            draft.status, draft.sent_at = DraftStatus.SENT, datetime.now(UTC)
        else:  # the owner wants to send it again: a fresh review and approval, and a new Message-ID
            draft.status, draft.approved_hash, draft.approved_at, draft.dispatch_at, draft.message_id, draft.attempts = DraftStatus.READY_FOR_REVIEW, None, None, None, None, 0
        return draft

    async def add_event(self, draft_id: str, event: str, detail: dict | None = None) -> None:
        self._events.append(EmailEvent(draft_id=draft_id, event=event, detail=detail or {}))

    async def list_events(self, draft_id: str) -> list[EmailEvent]:
        return [e for e in self._events if e.draft_id == draft_id]
