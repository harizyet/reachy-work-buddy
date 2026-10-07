"""Phase 27.1 foundation (docs/phase-27.md): the durable meeting record and
its job state machine. Meeting lives in companion-core only, not
shared/models — same precedent as tasks (ADR 0001) and calendar (ADR 0010);
nothing outside this service needs the wire contract yet.

27.1 drove UPLOADED->PREPROCESSING->TRANSCRIBING. 27.2/27.3 (ADR 0025) add
handlers for TRANSCRIBING and DIARIZING themselves, each calling its own
speech-inference sidecar (companion_core.meetings.speech_clients) — but
only when that sidecar is configured (worker.py's transcription_client/
diarization_client). Unlike PREPROCESSING, TRANSCRIBING and DIARIZING are
self-healing rather than claim-and-transition: the status name already
means "this stage's work has not yet succeeded," so a crash mid-call, a
transient sidecar outage, or no client configured at all all look the
same — the job simply rests there and is retried on the next poll,
without needing ORPHAN_RESUME. ALIGNING is claimed by the alignment stage (27.4) and ends at COMPLETE;
ANALYZING remains declared for later phases but is not reachable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MeetingJobStatus(StrEnum):
    UPLOADED = "uploaded"
    PREPROCESSING = "preprocessing"
    TRANSCRIBING = "transcribing"
    DIARIZING = "diarizing"
    ALIGNING = "aligning"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


# States a worker can still make progress from. Anything else (COMPLETE,
# FAILED, CANCELLED, or a later stage this codebase doesn't implement yet)
# is left alone.
WORKABLE_STATUSES = (
    MeetingJobStatus.UPLOADED,
    MeetingJobStatus.TRANSCRIBING,
    MeetingJobStatus.DIARIZING,
)

# A job found in one of these states at startup was mid-stage when the
# process last stopped, crash or not — no in-memory marker survives a
# restart to tell the two apart. Reset it to the start of that stage so the
# worker picks it up again (docs/phase-27.md 27.2: "A crashed worker must
# either resume the job safely or mark it failed"). Only PREPROCESSING
# needs this: it's the one stage whose status *is* the claim marker (see
# store.py's claim_next_upload). TRANSCRIBING/DIARIZING don't — see the
# module docstring.
ORPHAN_RESUME = {MeetingJobStatus.PREPROCESSING: MeetingJobStatus.UPLOADED}

# A meeting can be cancelled any time before it reaches a terminal state.
# Once at DIARIZING or later, cancelling does discard a completed
# transcript — that's an owner-initiated choice (e.g. "wrong recording"),
# not something this codebase should second-guess by refusing it.
CANCELLABLE_STATUSES = tuple(
    status for status in MeetingJobStatus if status not in (MeetingJobStatus.COMPLETE, MeetingJobStatus.FAILED, MeetingJobStatus.CANCELLED)
)


# 27.1 "Supported inputs should include at minimum: WAV; FLAC" plus the
# common formats it names as an FFmpeg-dependent stretch goal. No FFmpeg
# dependency exists in this codebase yet (27.1 doesn't require it), so
# these are accepted and stored, but only WAV gets a real duration probe
# in worker.py; other formats keep duration_seconds unset rather than a
# guessed value.
SUPPORTED_AUDIO_EXTENSIONS = frozenset({".wav", ".flac", ".m4a", ".aac", ".mp3", ".opus", ".webm"})


# States where nothing is running for the meeting, so it may be deleted: the job finished, failed, was cancelled, or is
# at ALIGNING, a quick in-process step with no recording work left to disturb.
DELETABLE_STATUSES = frozenset({
    MeetingJobStatus.COMPLETE, MeetingJobStatus.FAILED, MeetingJobStatus.CANCELLED, MeetingJobStatus.ALIGNING,
})
# States with a usable transcript for summaries, minutes and use as context.
READY_FOR_OUTPUTS = frozenset({MeetingJobStatus.ALIGNING, MeetingJobStatus.ANALYZING, MeetingJobStatus.COMPLETE})


class MeetingOutput(BaseModel):
    """A generated artefact. `tier` records which model wrote it ("local", "deep" or "cloud") so the owner can judge it
    and rerun it on a higher tier."""

    text: str
    tier: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Meeting(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    project_scope: str | None = None
    context: str | None = None
    participants: list[str] = Field(default_factory=list)
    # Owner-supplied meeting date/time (27.1 "Owner supplies optional
    # metadata"), distinct from created_at (upload time).
    started_at: datetime | None = None
    source_filename: str
    content_type: str
    audio_path: str
    normalized_audio_path: str | None = None
    duration_seconds: float | None = None
    # Raw sidecar output (27.2/27.3, ADR 0025): [{"start": s, "end": s,
    # "text": ...}] and [{"start": s, "end": s, "speaker": "SPEAKER_00"}]
    # respectively, exactly as companion_core.meetings.speech_clients
    # returns them. Not the canonical 27.4/27.5 aligned TranscriptSegment
    # model yet — that's a future reducer over both of these.
    transcript_segments: list[dict[str, Any]] | None = None
    diarization_segments: list[dict[str, Any]] | None = None
    # Phase 27.4: the transcript with a speaker on every segment, index-aligned with transcript_segments. Written once,
    # when the ALIGNING stage runs; None until then.
    aligned_segments: list[dict[str, Any]] | None = None
    # Owner-assigned display names, keyed by diarization label ("SPEAKER_00").
    # The raw diarization output is never rewritten (Phase 41, ADR 0030).
    speaker_names: dict[str, str] = Field(default_factory=dict)
    # Meeting-specific vocabulary (product, project and people names) that corrections are matched against.
    key_terms: list[str] = Field(default_factory=list)
    # Owner-accepted text for a transcript segment, keyed by its index as a
    # string. Overlays transcript_segments, which stays the raw ASR evidence.
    transcript_corrections: dict[str, str] = Field(default_factory=dict)
    summary: MeetingOutput | None = None
    minutes: MeetingOutput | None = None
    status: MeetingJobStatus = MeetingJobStatus.UPLOADED
    error_detail: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
