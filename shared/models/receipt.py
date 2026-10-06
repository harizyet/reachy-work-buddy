"""Authoritative record of what a deterministic handler did (Phase 39, ADR 0028).

Built by application code from persisted domain state, never from model text.
`fields` carries concise strings only: no conversation text, audio or prompts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ActionReceipt(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str = Field(max_length=64)
    status: Literal["success", "failed"] = "success"
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_channel: str = Field(max_length=32)
    object_type: str = Field(max_length=32)
    object_id: str | None = Field(default=None, max_length=100)
    fields: dict[str, str] = Field(default_factory=dict)
    failure_reason: str | None = Field(default=None, max_length=300)
    # Whether the hub should also push this to the owner's Telegram, and the
    # claim-once marker set when it has (same pattern as alarms' fired_at).
    notify: bool = False
    notified_at: datetime | None = None
