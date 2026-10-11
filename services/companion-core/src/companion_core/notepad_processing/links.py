"""Phase 49G: associating a note with a recorded meeting.

A link is a small record in its own table: it copies nothing and changes neither the note nor the meeting, so removing it deletes neither. Two ways to get one:

* EXPLICIT: the owner links a note to a meeting (including from inside that meeting), deterministically, confirmed at once.
* TEMPORAL: a SUGGESTION, never authoritative until the owner confirms it. It needs the meeting's actual occurrence time, `Meeting.started_at` (the time the owner or the recorder
  said the meeting happened), and compares the note's creation time with that window. `created_at` of the meeting (the upload time) is never used: a recording uploaded a week
  later still happened when it happened, and a meeting with no occurrence time can only be linked explicitly.

Suggestions are conservative on purpose: a note created long before or after a meeting is not suggested, a note merely edited during one is not suggested, overlapping meetings are
all offered and the owner picks, and a pair the owner already confirmed or rejected is never suggested again."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from companion_core.meetings.models import READY_FOR_OUTPUTS, Meeting, MeetingJobStatus
from companion_core.notepad_processing.models import MeetingLink, normalise

BEFORE = timedelta(minutes=10)  # people open a note a little before the meeting starts
AFTER = timedelta(minutes=15)  # ... and finish it a little after it ends
MAX_SUGGESTIONS = 3


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def occurrence(meeting: Meeting) -> tuple[datetime, datetime] | None:
    """When the meeting actually happened, or None when that is not known. Never the upload time."""
    if meeting.started_at is None:
        return None
    start = _aware(meeting.started_at)
    if meeting.duration_seconds:
        return start, start + timedelta(seconds=meeting.duration_seconds)
    segments = meeting.transcript_segments or []
    if segments:
        return start, start + timedelta(seconds=float(segments[-1].get("end", 0)))
    return None  # the end is unknown (no duration probe, no transcript yet): not enough to compare a time window


def transcript_ready(meeting: Meeting) -> bool:
    return meeting.status in READY_FOR_OUTPUTS and bool(meeting.transcript_segments)


def suggestion(note, meeting: Meeting) -> MeetingLink | None:
    """A suggested link when the note was created during the meeting (give or take BEFORE / AFTER), else None."""
    if meeting.status is MeetingJobStatus.CANCELLED:
        return None
    window = occurrence(meeting)
    if window is None:
        return None
    start, end = window
    created = _aware(note.created_at)
    if not (start - BEFORE <= created <= end + AFTER):
        return None
    updated = max(_aware(note.updated_at), created)
    overlap = max(0.0, (min(updated, end) - max(created, start)).total_seconds())
    title = normalise(meeting.title)
    mentioned = len(title) >= 4 and (title in normalise(note.title) or title in normalise(note.body[:300]))
    return MeetingLink(note_id=note.id, meeting_id=meeting.id, source="temporal", state="suggested", overlap_seconds=int(overlap), title_match=mentioned)


def rank(note, link: MeetingLink, meeting: Meeting) -> tuple:
    start = occurrence(meeting)[0]
    return (not link.title_match, -(link.overlap_seconds or 0), abs((_aware(note.created_at) - start).total_seconds()))


def meeting_view(meeting: Meeting | None) -> dict | None:
    if meeting is None:
        return None
    window = occurrence(meeting)
    return {"id": meeting.id, "title": meeting.title, "status": meeting.status.value, "started_at": meeting.started_at.isoformat() if meeting.started_at else None,
            "ends_at": window[1].isoformat() if window else None, "transcript_ready": transcript_ready(meeting)}
