"""Phase 27.1 foundation (docs/phase-27.md): the durable meeting record and
its job state machine. Meeting lives in companion-core only, not
shared/models — same precedent as tasks (ADR 0001) and calendar (ADR 0010);
nothing outside this service needs the wire contract yet.

Only the 27.1 Foundation states are driven automatically: a worker moves a
job from UPLOADED through PREPROCESSING and leaves it at TRANSCRIBING,
because no local long-form STT integration exists yet (that's 27.2). A job
resting at TRANSCRIBING is not stuck or broken — it is correctly waiting
for a stage this codebase doesn't implement yet, the same
honesty-about-scope other placeholder pieces here use. DIARIZING, ALIGNING,
ANALYZING and COMPLETE are declared for the full 27.1-27.9 sequence but are
not reachable until their phases add a handler.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

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
WORKABLE_STATUSES = (MeetingJobStatus.UPLOADED,)

# A job found in one of these states at startup was mid-stage when the
# process last stopped, crash or not — no in-memory marker survives a
# restart to tell the two apart. Reset it to the start of that stage so the
# worker picks it up again (docs/phase-27.md 27.2: "A crashed worker must
# either resume the job safely or mark it failed").
ORPHAN_RESUME = {MeetingJobStatus.PREPROCESSING: MeetingJobStatus.UPLOADED}

# A meeting can only be cancelled before real processing work has produced
# anything worth keeping.
CANCELLABLE_STATUSES = (MeetingJobStatus.UPLOADED, MeetingJobStatus.PREPROCESSING)


# 27.1 "Supported inputs should include at minimum: WAV; FLAC" plus the
# common formats it names as an FFmpeg-dependent stretch goal. No FFmpeg
# dependency exists in this codebase yet (27.1 doesn't require it), so
# these are accepted and stored, but only WAV gets a real duration probe
# in worker.py; other formats keep duration_seconds unset rather than a
# guessed value.
SUPPORTED_AUDIO_EXTENSIONS = frozenset({".wav", ".flac", ".m4a", ".aac", ".mp3", ".opus", ".webm"})


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
    status: MeetingJobStatus = MeetingJobStatus.UPLOADED
    error_detail: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
