"""CalendarEvent lives in companion-core only, not shared/models — per ADR
0001, calendar is exclusively companion-core's (reachy-hub never needs to
construct or validate one, only relay opaque JSON from companion-core's
HTTP responses, the same way it already treats companion-core's
conversation replies)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    start: datetime
    end: datetime
    location: str | None = None
