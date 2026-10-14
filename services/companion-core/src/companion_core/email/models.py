"""EmailMessage/EmailDraft live in companion-core only, not shared/models —
same reasoning as calendar/tasks (ADR 0001): email is exclusively
companion-core's, reachy-hub only relays opaque JSON from its HTTP
responses.

`EmailMessage` is a *received* message — there's no real IMAP/inbox sync
here (no external email credential available), so, same
graceful-degradation pattern as calendar's lack of external calendar sync,
these are seeded through an operator/setup API rather than pulled from a
real mailbox.

`EmailDraft.status` is the mechanism behind Phase 14's exit criterion ("No
code path sends mail without approval gate") and docs/adr/0011's delayed-
send requirement: DRAFT -> APPROVED (explicit `POST
/emails/drafts/{id}/approve`, text-only per the ADR) -> QUEUED ("send
draft X", also text-only — `dispatch_at` set ~10 minutes out) -> SENT,
once `email/workflow.py`'s background dispatch loop — the only code that
ever invokes an `EmailSender` — actually sends it. QUEUED -> CANCELLED is
the undo: any channel, any modality, always allowed, since undoing is the
safe direction and should never be harder than the destructive action
itself.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

TEXT_KIND = "text"  # a draft written in conversation: one recipient, no attachment (the original kind)
MEETING_MINUTES_KIND = "meeting_minutes"
SENDER_TEST_KIND = "sender_test"  # the owner's one-off test of the dedicated sender: fixed text, one recipient, no meeting content


class DraftStatus(StrEnum):
    DRAFT = "draft"
    # Phase 55 (meeting minutes): a prepared package waiting for the owner's review, and the states of a send in progress or with an unsettled outcome.
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"  # nothing was delivered: refused, authentication failed, or retries ran out
    UNKNOWN_DELIVERY = "unknown_delivery"  # the server may or may not have accepted it: never retried automatically


class EmailMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str
    subject: str
    body: str
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Recipients(BaseModel):
    """The complete delivery list. Every address is lower-case and validated (email/mime.py); Bcc is kept apart so a preview can show it and the message headers never do."""

    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)

    def everyone(self) -> list[str]:
        return list(dict.fromkeys([*self.to, *self.cc, *self.bcc]))


class AttachmentMeta(BaseModel):
    name: str
    content_type: str
    sha256: str
    size: int


class EmailDraft(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    to: str
    subject: str
    body: str
    in_reply_to: str | None = None
    status: DraftStatus = DraftStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_at: datetime | None = None
    dispatch_at: datetime | None = None
    sent_at: datetime | None = None
    # Phase 55. All defaulted, so drafts written in conversation validate unchanged.
    kind: str = TEXT_KIND
    recipients: Recipients | None = None  # None for a text draft: `to` is its one recipient
    attachments: list[AttachmentMeta] = Field(default_factory=list)
    source: dict | None = None  # what the package was prepared from (meeting id, output revisions, speaker-name fingerprint), frozen at preparation
    package_hash: str | None = None  # hash of exactly what would be sent
    approved_hash: str | None = None  # the package hash the owner approved; a send needs the two to be equal
    message_id: str | None = None  # RFC 5322 Message-ID, chosen once so every attempt and any reconciliation refers to the same message
    sender: str | None = None
    attempts: int = 0
    claimed_at: datetime | None = None
    last_error: str | None = None
    provider_response: str | None = None  # the server's acceptance line when it gave one
    # Loaded by the dispatch loop just before sending, never serialised or hashed: (file name, content type, bytes). The bytes are the ones the owner previewed and approved.
    attachment_blobs: list[tuple[str, str, bytes]] = Field(default_factory=list, exclude=True)


def package_hash(draft: EmailDraft, sender: str | None) -> str:
    """Identity of the exact delivery package: sender, complete recipient list, subject, body, each attachment's hash, and the source revision. Approval is bound to this value."""
    rec = draft.recipients or Recipients(to=[draft.to] if draft.to else [])
    payload = {
        "kind": draft.kind, "sender": sender, "to": sorted(rec.to), "cc": sorted(rec.cc), "bcc": sorted(rec.bcc), "subject": draft.subject, "body": draft.body,
        "attachments": sorted((a.name, a.content_type, a.sha256, a.size) for a in draft.attachments), "source": draft.source,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


class EmailEvent(BaseModel):
    """One line of a draft's history: who did what, when, with non-secret detail."""

    draft_id: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event: str
    detail: dict = Field(default_factory=dict)

