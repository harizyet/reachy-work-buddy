"""MeetingStore owns both the durable Meeting row and its raw audio bytes —
unlike every other store in this codebase, a meeting's "content" is a
binary blob too large to treat like a text field. See postgres_store.py for
why audio lives on disk rather than in a column.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any, BinaryIO, Protocol

from companion_core.meetings.models import (
    CANCELLABLE_STATUSES,
    ORPHAN_RESUME,
    Meeting,
    MeetingJobStatus,
    MeetingOutput,
)


class MeetingNotCancellableError(Exception):
    pass


class MeetingStore(Protocol):
    async def create_meeting(
        self,
        *,
        title: str,
        audio: bytes | BinaryIO,
        source_filename: str,
        content_type: str,
        project_scope: str | None = None,
        context: str | None = None,
        participants: list[str] | None = None,
        started_at: datetime | None = None,
    ) -> Meeting: ...

    async def get_meeting(self, meeting_id: str) -> Meeting | None: ...
    async def list_meetings(self) -> list[Meeting]: ...
    async def load_audio(self, meeting_id: str) -> bytes: ...
    async def open_audio(self, meeting_id: str) -> BinaryIO:
        """Return a seekable stream; the caller owns closing it."""
        ...

    async def claim_next_upload(self) -> Meeting | None:
        """Atomically move the oldest UPLOADED job to PREPROCESSING and
        return it, or None if nothing is waiting."""
        ...

    async def requeue_orphaned(self) -> int:
        """Startup recovery: reset any job left mid-stage by a process that
        stopped without finishing it. Returns how many were reset."""
        ...

    async def mark_preprocessed(
        self, meeting_id: str, *, normalized_audio_path: str | None, duration_seconds: float | None
    ) -> Meeting | None: ...

    async def claim_next_transcription(self) -> Meeting | None:
        """The oldest TRANSCRIBING job, or None. Unlike claim_next_upload
        this does not change status — TRANSCRIBING already means "not
        transcribed yet"; see models.py's module docstring."""
        ...

    async def claim_next_diarization(self) -> Meeting | None:
        """The oldest DIARIZING job, or None. Same non-transitioning shape
        as claim_next_transcription."""
        ...

    async def mark_transcribed(
        self, meeting_id: str, *, transcript_segments: list[dict[str, Any]]
    ) -> Meeting | None: ...

    async def mark_diarized(
        self, meeting_id: str, *, diarization_segments: list[dict[str, Any]]
    ) -> Meeting | None: ...

    async def claim_next_alignment(self) -> Meeting | None:
        """The oldest ALIGNING job, or None. Same non-transitioning shape as claim_next_diarization."""
        ...

    async def mark_aligned(self, meeting_id: str, *, aligned_segments: list[dict[str, Any]]) -> Meeting | None:
        """Store the aligned transcript and complete the job. A no-op unless the job is still ALIGNING."""
        ...

    async def claim_next_audio_check(self) -> Meeting | None:
        """A finished meeting whose recording has not been checked for silent stretches yet, or None."""
        ...

    async def set_audio_gaps(self, meeting_id: str, gaps: dict[str, Any]) -> Meeting | None: ...

    async def mark_failed(self, meeting_id: str, *, error_detail: str) -> Meeting | None: ...
    async def cancel_meeting(self, meeting_id: str) -> Meeting | None: ...
    async def set_speaker_names(self, meeting_id: str, names: dict[str, str]) -> Meeting | None:
        """Replace the whole speaker-name map."""
        ...

    async def set_correction(self, meeting_id: str, segment: int, text: str | None) -> Meeting | None:
        """Overlay text for one transcript segment; None removes the overlay."""
        ...

    async def set_corrections(self, meeting_id: str, updates: dict[int, str]) -> Meeting | None:
        """Overlay several segments in one write."""
        ...

    async def set_key_terms(self, meeting_id: str, terms: list[str]) -> Meeting | None:
        """Replace this meeting's vocabulary."""
        ...

    async def list_terms(self) -> list[str]:
        """The owner's global glossary, alphabetical."""
        ...

    async def set_output(self, meeting_id: str, kind: str, output: MeetingOutput | None) -> Meeting | None:
        """Store (or with None clear) the generated summary or minutes."""
        ...

    async def delete_meeting(self, meeting_id: str) -> bool:
        """Remove the record and its audio. The caller has already checked the meeting is in a deletable state."""
        ...

    async def add_term(self, term: str) -> None: ...

    async def delete_term(self, term: str) -> bool: ...


class InMemoryMeetingStore:
    def __init__(self) -> None:
        self._meetings: dict[str, Meeting] = {}
        self._audio: dict[str, bytes] = {}
        self._terms: dict[str, str] = {}

    async def create_meeting(
        self,
        *,
        title: str,
        audio: bytes | BinaryIO,
        source_filename: str,
        content_type: str,
        project_scope: str | None = None,
        context: str | None = None,
        participants: list[str] | None = None,
        started_at: datetime | None = None,
    ) -> Meeting:
        meeting = Meeting(
            title=title,
            source_filename=source_filename,
            content_type=content_type,
            audio_path=source_filename,
            project_scope=project_scope,
            context=context,
            participants=list(participants or []),
            started_at=started_at,
        )
        self._meetings[meeting.id] = meeting
        self._audio[meeting.id] = audio if isinstance(audio, bytes) else audio.read()
        return meeting

    async def get_meeting(self, meeting_id: str) -> Meeting | None:
        return self._meetings.get(meeting_id)

    async def list_meetings(self) -> list[Meeting]:
        return sorted(self._meetings.values(), key=lambda m: m.created_at, reverse=True)

    async def load_audio(self, meeting_id: str) -> bytes:
        return self._audio[meeting_id]

    async def open_audio(self, meeting_id: str) -> BinaryIO:
        return BytesIO(self._audio[meeting_id])

    def _touch(self, meeting: Meeting, **fields) -> Meeting:
        updated = meeting.model_copy(update={**fields, "updated_at": datetime.now(UTC)})
        self._meetings[updated.id] = updated
        return updated

    async def claim_next_upload(self) -> Meeting | None:
        candidates = [m for m in self._meetings.values() if m.status == MeetingJobStatus.UPLOADED]
        if not candidates:
            return None
        oldest = min(candidates, key=lambda m: m.created_at)
        return self._touch(oldest, status=MeetingJobStatus.PREPROCESSING)

    async def requeue_orphaned(self) -> int:
        count = 0
        for meeting in list(self._meetings.values()):
            resume_to = ORPHAN_RESUME.get(meeting.status)
            if resume_to is not None:
                self._touch(meeting, status=resume_to)
                count += 1
        return count

    async def mark_preprocessed(
        self, meeting_id: str, *, normalized_audio_path: str | None, duration_seconds: float | None
    ) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        # A cancel can race a stage that's already in flight (single
        # bounded worker, but an owner-initiated cancel is a separate
        # HTTP request) — once cancelled/failed, a late stage completion
        # must not resurrect the job. No-op, return the current row.
        if meeting.status != MeetingJobStatus.PREPROCESSING:
            return meeting
        return self._touch(
            meeting,
            status=MeetingJobStatus.TRANSCRIBING,
            normalized_audio_path=normalized_audio_path,
            duration_seconds=duration_seconds,
        )

    async def claim_next_transcription(self) -> Meeting | None:
        candidates = [m for m in self._meetings.values() if m.status == MeetingJobStatus.TRANSCRIBING]
        return min(candidates, key=lambda m: m.created_at) if candidates else None

    async def claim_next_diarization(self) -> Meeting | None:
        candidates = [m for m in self._meetings.values() if m.status == MeetingJobStatus.DIARIZING]
        return min(candidates, key=lambda m: m.created_at) if candidates else None

    async def mark_transcribed(
        self, meeting_id: str, *, transcript_segments: list[dict[str, Any]]
    ) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        if meeting.status != MeetingJobStatus.TRANSCRIBING:  # see mark_preprocessed's comment
            return meeting
        return self._touch(
            meeting, status=MeetingJobStatus.DIARIZING, transcript_segments=transcript_segments
        )

    async def claim_next_alignment(self) -> Meeting | None:
        candidates = [m for m in self._meetings.values() if m.status == MeetingJobStatus.ALIGNING]
        return min(candidates, key=lambda m: m.created_at) if candidates else None

    async def mark_aligned(self, meeting_id: str, *, aligned_segments: list[dict[str, Any]]) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        if meeting.status != MeetingJobStatus.ALIGNING:
            return meeting
        return self._touch(meeting, status=MeetingJobStatus.COMPLETE, aligned_segments=aligned_segments)

    async def claim_next_audio_check(self) -> Meeting | None:
        candidates = [m for m in self._meetings.values() if m.status == MeetingJobStatus.COMPLETE and m.audio_gaps is None]
        return min(candidates, key=lambda m: m.created_at) if candidates else None

    async def set_audio_gaps(self, meeting_id: str, gaps: dict[str, Any]) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        return self._touch(meeting, audio_gaps=gaps) if meeting else None

    async def mark_diarized(
        self, meeting_id: str, *, diarization_segments: list[dict[str, Any]]
    ) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        if meeting.status != MeetingJobStatus.DIARIZING:  # see mark_preprocessed's comment
            return meeting
        return self._touch(
            meeting, status=MeetingJobStatus.ALIGNING, diarization_segments=diarization_segments
        )

    async def mark_failed(self, meeting_id: str, *, error_detail: str) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        return self._touch(meeting, status=MeetingJobStatus.FAILED, error_detail=error_detail)

    async def cancel_meeting(self, meeting_id: str) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        if meeting.status not in CANCELLABLE_STATUSES:
            raise MeetingNotCancellableError(f"meeting '{meeting_id}' is past the cancellable stage")
        return self._touch(meeting, status=MeetingJobStatus.CANCELLED)

    async def set_speaker_names(self, meeting_id: str, names: dict[str, str]) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        return None if meeting is None else self._touch(meeting, speaker_names=dict(names))

    async def set_correction(self, meeting_id: str, segment: int, text: str | None) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        corrections = dict(meeting.transcript_corrections)
        if text is None:
            corrections.pop(str(segment), None)
        else:
            corrections[str(segment)] = text
        return self._touch(meeting, transcript_corrections=corrections)

    async def set_corrections(self, meeting_id: str, updates: dict[int, str]) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        if meeting is None:
            return None
        merged = {**meeting.transcript_corrections, **{str(i): t for i, t in updates.items()}}
        return self._touch(meeting, transcript_corrections=merged)

    async def set_key_terms(self, meeting_id: str, terms: list[str]) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        return None if meeting is None else self._touch(meeting, key_terms=list(terms))

    async def list_terms(self) -> list[str]:
        return sorted(self._terms.values(), key=str.lower)

    async def add_term(self, term: str) -> None:
        self._terms.setdefault(term.lower(), term)

    async def delete_term(self, term: str) -> bool:
        return self._terms.pop(term.lower(), None) is not None

    async def set_output(self, meeting_id: str, kind: str, output: MeetingOutput | None) -> Meeting | None:
        meeting = self._meetings.get(meeting_id)
        return None if meeting is None else self._touch(meeting, **{kind: output})

    async def delete_meeting(self, meeting_id: str) -> bool:
        self._audio.pop(meeting_id, None)
        return self._meetings.pop(meeting_id, None) is not None
