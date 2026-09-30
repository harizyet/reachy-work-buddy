"""Bounded in-process meeting-job worker (docs/phase-27.md 27.2/27.3, ADR
0025). No Redis or external queue — a single asyncio task polls
MeetingStore for workable jobs, exactly as 27.1 Foundation specifies.

PREPROCESSING probes WAV duration with the stdlib `wave` module (no
FFmpeg dependency exists in this codebase yet; see models.py's
SUPPORTED_AUDIO_EXTENSIONS comment). TRANSCRIBING and DIARIZING each call
their own speech-inference sidecar through the client seam in
speech_clients.py — but only when that client is configured
(`transcription_client`/`diarization_client` below). Without one, a job
simply rests at that status, same honesty-about-scope as before ADR
0025: no sidecar deployed is not an error, it's a feature that hasn't
been turned on.

TRANSCRIBING/DIARIZING are self-healing rather than claim-and-transition
(see models.py's module docstring): a `SpeechServiceUnavailable` (sidecar
down/timed out) leaves the job's status untouched for the next poll to
retry, rather than failing the meeting over what is likely a transient
deployment issue. Only a `SpeechServiceRejected` (the sidecar understood
the request and refused it) or an unexpected exception fails the job.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import wave
from io import BytesIO

from companion_core.meetings.models import Meeting
from companion_core.meetings.speech_clients import (
    DiarizationClient,
    SpeechServiceRejected,
    SpeechServiceUnavailable,
    TranscriptionClient,
)
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


async def preprocess(store: MeetingStore, meeting: Meeting) -> bool:
    """Always makes progress (success or permanent failure) — unlike
    transcribe()/diarize() below, this has no external-service dependency
    that could be transiently unavailable, so there is no "try again
    later" case here."""
    try:
        audio = await store.load_audio(meeting.id)
    except (KeyError, OSError) as exc:
        await store.mark_failed(meeting.id, error_detail=f"could not read uploaded audio: {exc}")
        return True
    if not audio:
        await store.mark_failed(meeting.id, error_detail="uploaded audio file is empty")
        return True
    duration = await asyncio.to_thread(probe_wav_duration, audio) if meeting.content_type == "audio/wav" else None
    await store.mark_preprocessed(meeting.id, normalized_audio_path=None, duration_seconds=duration)
    return True


async def transcribe(store: MeetingStore, meeting: Meeting, client: TranscriptionClient) -> bool:
    """Returns whether the attempt made progress (succeeded or permanently
    failed) — False means "try again later", matching process_one's
    found/not-found shape so a down sidecar doesn't spin the poll loop."""
    try:
        audio = await store.load_audio(meeting.id)
    except (KeyError, OSError) as exc:
        await store.mark_failed(meeting.id, error_detail=f"could not read audio for transcription: {exc}")
        return True
    try:
        segments = await client.transcribe(
            audio, filename=meeting.source_filename, content_type=meeting.content_type
        )
    except SpeechServiceUnavailable as exc:
        logger.warning("meeting %s: transcription service unavailable, will retry: %s", meeting.id, exc)
        return False
    except SpeechServiceRejected as exc:
        await store.mark_failed(meeting.id, error_detail=f"transcription rejected: {exc}")
        return True
    await store.mark_transcribed(meeting.id, transcript_segments=segments)
    return True


async def diarize(store: MeetingStore, meeting: Meeting, client: DiarizationClient) -> bool:
    """Same shape as transcribe() above."""
    try:
        audio = await store.load_audio(meeting.id)
    except (KeyError, OSError) as exc:
        await store.mark_failed(meeting.id, error_detail=f"could not read audio for diarization: {exc}")
        return True
    try:
        segments = await client.diarize(audio, filename=meeting.source_filename, content_type=meeting.content_type)
    except SpeechServiceUnavailable as exc:
        logger.warning("meeting %s: diarization service unavailable, will retry: %s", meeting.id, exc)
        return False
    except SpeechServiceRejected as exc:
        await store.mark_failed(meeting.id, error_detail=f"diarization rejected: {exc}")
        return True
    await store.mark_diarized(meeting.id, diarization_segments=segments)
    return True


class MeetingWorker:
    def __init__(
        self,
        store: MeetingStore,
        *,
        transcription_client: TranscriptionClient | None = None,
        diarization_client: DiarizationClient | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self._store = store
        self._transcription_client = transcription_client
        self._diarization_client = diarization_client
        self._poll_interval = poll_interval

    async def _try_stage(self, claim, run_stage, error_label: str) -> bool | None:
        """Returns True (made progress), False (found but not ready to
        retry yet — e.g. sidecar transiently unavailable), or None
        (nothing waiting in this stage)."""
        meeting = await claim()
        if meeting is None:
            return None
        try:
            return await run_stage(meeting)
        except Exception as exc:  # a crashed stage must fail the job, not the worker loop
            logger.exception("meeting %s %s failed", meeting.id, error_label)
            with contextlib.suppress(Exception):
                await self._store.mark_failed(meeting.id, error_detail=f"{error_label} error: {exc}")
            return True

    async def process_one(self) -> bool:
        """Try each stage in pipeline order and return on the first one
        that makes progress, so one busy/stuck stage (e.g. the
        transcription sidecar transiently down) does not starve the
        others. Returns whether any progress was made anywhere, so
        run_forever can poll faster while there's a backlog and back off
        only once every stage found nothing to do or nothing it could do
        yet."""
        stages = [(self._store.claim_next_upload, lambda m: preprocess(self._store, m), "preprocessing")]
        if self._transcription_client is not None:
            stages.append((
                self._store.claim_next_transcription,
                lambda m: transcribe(self._store, m, self._transcription_client),
                "transcription",
            ))
        if self._diarization_client is not None:
            stages.append((
                self._store.claim_next_diarization,
                lambda m: diarize(self._store, m, self._diarization_client),
                "diarization",
            ))

        for claim, run_stage, error_label in stages:
            result = await self._try_stage(claim, run_stage, error_label)
            if result:
                return True
        return False

    async def run_forever(self) -> None:
        resumed = await self._store.requeue_orphaned()
        if resumed:
            logger.warning("meetings: requeued %d job(s) left mid-stage by a previous run", resumed)
        while True:
            found = await self.process_one()
            if not found:
                await asyncio.sleep(self._poll_interval)
