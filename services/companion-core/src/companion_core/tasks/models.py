"""Task lives in companion-core only, not shared/models — per ADR 0001,
tasks are exclusively companion-core's, same as calendar (ADR 0010).

Unlike calendar and email, docs/plan.md's routing table doesn't call tasks
out as inherently privacy-sensitive, so task-related replies go through the
normal classify_privacy(text) path rather than an unconditional override —
see task_intent.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    OPEN = "open"
    DONE = "done"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    status: TaskStatus = TaskStatus.OPEN
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
