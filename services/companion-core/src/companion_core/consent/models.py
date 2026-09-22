"""ConfirmationRequest lives in companion-core only, not shared/models —
same reasoning as calendar/tasks/email (ADR 0001): the consent gate is
exclusively companion-core's, since that's where every destructive
tool/store lives. See docs/adr/0011-destructive-action-consent.md for the
full design; gate.py is where the two hard rules (no voice, no bulk) are
actually enforced — this module is just the data shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"


class ActionScope(StrEnum):
    """SINGLE targets one identified record. BULK targets an unbounded or
    mass set ("delete all memories", "empty the mailbox") — gate.py's
    request_confirmation refuses to even create a BULK confirmation, ever,
    regardless of who's asking or how they'd confirm it. There is no
    scope besides these two; a new bulk-capable tool must not invent a
    third scope to route around the block."""

    SINGLE = "single"
    BULK = "bulk"


class ConfirmationRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str
    target_id: str
    description: str
    scope: ActionScope = ActionScope.SINGLE
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    confirmed_at: datetime | None = None
