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

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DraftStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    QUEUED = "queued"
    SENT = "sent"
    CANCELLED = "cancelled"
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
    dispatch_at: datetime | None = None
    sent_at: datetime | None = None
