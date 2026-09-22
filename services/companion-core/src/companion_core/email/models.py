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
code path sends mail without approval gate"): a draft starts at DRAFT, an
explicit `POST /emails/drafts/{id}/approve` call moves it to APPROVED, and
only `email/workflow.py`'s `send_approved_draft` — the single function
anywhere in this codebase that invokes an `EmailSender` — will actually
dispatch a draft, and only once it's checked the status is APPROVED.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DraftStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    REJECTED = "rejected"


class EmailMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str
    subject: str
    body: str
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EmailDraft(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    to: str
    subject: str
    body: str
    in_reply_to: str | None = None
    status: DraftStatus = DraftStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_at: datetime | None = None
    sent_at: datetime | None = None
