"""Bounded in-process meeting-job worker (docs/phase-27.md 27.2). No Redis
or external queue — a single asyncio task polls MeetingStore for workable
jobs, exactly as that section specifies for 27.1 Foundation.

Only PREPROCESSING is implemented: it probes WAV duration with the
stdlib `wave` module (no FFmpeg dependency exists in this codebase yet;
see models.py's SUPPORTED_AUDIO_EXTENSIONS comment) and then hands the job
to TRANSCRIBING, where it waits — 27.2 (long-form STT) is what will next
claim TRANSCRIBING jobs. This worker does not do that yet.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import wave
from io import BytesIO

from companion_core.meetings.models import Meeting
from companion_core.meetings.store import MeetingStore

logger = logging.getLogger(__name__)


def probe_wav_duration(audio: bytes) -> float | None:
    """Real duration for a standard WAV file; None for anything else
    (including a malformed WAV) rather than a guessed value."""
    try:
        with wave.open(BytesIO(audio)) as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if rate <= 0:
                return None
            return frames / rate
    except (wave.Error, EOFError):
        return None


async def preprocess(store: MeetingStore, meeting: Meeting) -> Meeting | None:
    try:
        audio = await store.load_audio(meeting.id)
    except (KeyError, OSError) as exc:
        return await store.mark_failed(meeting.id, error_detail=f"could not read uploaded audio: {exc}")
    if not audio:
        return await store.mark_failed(meeting.id, error_detail="uploaded audio file is empty")
    duration = await asyncio.to_thread(probe_wav_duration, audio) if meeting.content_type == "audio/wav" else None
    return await store.mark_preprocessed(meeting.id, normalized_audio_path=None, duration_seconds=duration)


class MeetingWorker:
    def __init__(self, store: MeetingStore, *, poll_interval: float = 2.0) -> None:
        self._store = store
        self._poll_interval = poll_interval

    async def process_one(self) -> bool:
        """Claim and process a single workable job. Returns whether one was
        found, so run_forever can poll faster while there's a backlog."""
        meeting = await self._store.claim_next_upload()
        if meeting is None:
            return False
        try:
            await preprocess(self._store, meeting)
        except Exception as exc:  # a crashed stage must fail the job, not the worker loop
            logger.exception("meeting %s preprocessing failed", meeting.id)
            with contextlib.suppress(Exception):
                await self._store.mark_failed(meeting.id, error_detail=f"preprocessing error: {exc}")
        return True

    async def run_forever(self) -> None:
        resumed = await self._store.requeue_orphaned()
        if resumed:
            logger.warning("meetings: requeued %d job(s) left mid-stage by a previous run", resumed)
        while True:
            found = await self.process_one()
            if not found:
                await asyncio.sleep(self._poll_interval)
