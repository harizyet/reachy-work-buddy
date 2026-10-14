"""CalendarEvent lives in companion-core only, not shared/models — per ADR
0001, calendar is exclusively companion-core's (reachy-hub never needs to
construct or validate one, only relay opaque JSON from companion-core's
HTTP responses, the same way it already treats companion-core's
conversation replies).

The fields after `busy` were added with the read-only ICS feed (ADR 0035). They
all have defaults, so events from the local store and from Google keep
validating unchanged; only events from a feed carry a source identity.
"""

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
    busy: bool = Field(default=True, exclude=True)
    # Classification (calendar/classify.py). `classification` is None only until an event has been through the classifier.
    all_day: bool = False
    classification: str | None = None
    classification_basis: str | None = None  # explicit | rule | owner
    classification_reasons: list[str] = Field(default_factory=list)
    status: str = "confirmed"  # confirmed | tentative | cancelled
    response: str | None = None  # the owner's own answer when the feed says it: accepted | declined | tentative | needs-action
    redacted: bool = False  # the source hid the details; title is the placeholder "Busy" and no detail is kept
    title_missing: bool = False  # the source gave no title; `title` is a display placeholder, never a guess
    source: str = "local"  # local | ics | google
    event_key: str | None = None  # stable identity of this occurrence across refreshes (the recurrence id is the original start)
    series_key: str | None = None  # stable identity of the whole series
    recurring: bool = False
    remind: bool = False  # a recording reminder is created for this occurrence
    remind_blocked: str | None = None  # why not, when it is not
