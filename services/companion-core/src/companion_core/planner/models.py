"""Owner's notes and timed reminders, entered through the web UI.

Both live in companion-core only (ADR 0001, same as tasks). A reminder is a
typed text with a due time, unrelated to calendar-derived reminders.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from shared.models.response import Privacy


def _now() -> datetime:
    return datetime.now(UTC)


class Note(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    body: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    # Phase 44A: unclassified means work-private; project_scope None means unscoped (not public). Editing a note never
    # changes either.
    sensitivity: Privacy = Privacy.WORK_PRIVATE
    project_scope: str | None = None


class ReminderStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"


class Reminder(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    due_at: datetime
    status: ReminderStatus = ReminderStatus.PENDING
    created_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    notified_at: datetime | None = None
    sensitivity: Privacy = Privacy.WORK_PRIVATE


class AlarmStatus(StrEnum):
    SCHEDULED = "scheduled"
    FIRED = "fired"
    CANCELLED = "cancelled"


class Alarm(BaseModel):
    """Phase 38 (ADR 0027). Notification/playback only; the hub decides how
    a due alarm is delivered. `fired_at` is the claim-once marker."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    due_at: datetime
    reminder_id: str | None = None
    station_id: str | None = None
    status: AlarmStatus = AlarmStatus.SCHEDULED
    created_at: datetime = Field(default_factory=_now)
    fired_at: datetime | None = None
    delivery: str | None = None
    volume: int = Field(default=100, ge=10, le=400)
    # Weekdays (0 = Monday … 6 = Sunday) the alarm repeats on; empty rings once. `enabled` is the clock's on/off switch.
    repeat: list[int] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("repeat")
    @classmethod
    def _valid_days(cls, days: list[int]) -> list[int]:
        if any(not 0 <= d <= 6 for d in days):
            raise ValueError("repeat days are 0 (Monday) to 6 (Sunday)")
        return sorted(set(days))


class Station(BaseModel):
    """An owner-saved TuneIn station. Only TuneIn's guide id is kept: the
    stream URL is resolved when an alarm plays, never stored or supplied by
    a client (ADR 0027)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    guide_id: str
    created_at: datetime = Field(default_factory=_now)
