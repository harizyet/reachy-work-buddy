"""Stretches of a recording with no captured audio (the phone handed the app digital silence)."""

import asyncio
import io
import wave

import numpy as np
from companion_core.meetings import silence
from companion_core.meetings.models import MeetingJobStatus
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.meetings.worker import MeetingWorker

RATE = 16000


def wav(*parts: tuple[float, bool]) -> bytes:
    """Seconds of a tone (True) or exact zeros (False), in order."""
    chunks = []
    for seconds, sound in parts:
        t = np.arange(int(RATE * seconds)) / RATE
        chunks.append((6000 * np.sin(2 * np.pi * 300 * t)).astype("<i2") if sound else np.zeros(len(t), dtype="<i2"))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(np.concatenate(chunks).tobytes())
    return buffer.getvalue()


def seg(start: float, end: float) -> dict:
    return {"start": start, "end": end, "text": "words"}


def test_a_long_run_of_zeros_is_found_and_ordinary_pauses_are_not() -> None:
    audio = wav((3, True), (8, False), (3, True), (2, False), (3, True))  # an 8 s gap and a 2 s pause
    gaps = silence.analyse(io.BytesIO(audio), [seg(0, 3), seg(2, 12), seg(11, 14), seg(14, 16)])
    assert [(round(s["start"]), round(s["end"])) for s in gaps["spans"]] == [(3, 11)]
    assert gaps["segments"] == [1]  # mostly inside the gap; the line that only touches it, and the short pause, are not
    assert gaps["seconds"] == 8.0


def test_a_recording_with_sound_throughout_has_no_gaps() -> None:
    assert silence.analyse(io.BytesIO(wav((6, True))), [seg(0, 6)]) == {"spans": [], "segments": [], "seconds": 0.0}


def test_the_worker_checks_a_finished_meeting_once_and_never_fails_it() -> None:
    store = InMemoryMeetingStore()

    async def run():
        good = await store.create_meeting(title="gap", audio=wav((3, True), (8, False), (3, True)), source_filename="m.wav", content_type="audio/wav")
        bad = await store.create_meeting(title="not audio", audio=b"x", source_filename="m.m4a", content_type="audio/mp4")
        for m in (good, bad):
            store._touch(m, status=MeetingJobStatus.COMPLETE, transcript_segments=[seg(3.5, 10.5)])
        worker = MeetingWorker(store)
        assert await worker.process_one() is True and await worker.process_one() is True
        assert await worker.process_one() is False
        checked = await store.get_meeting(good.id)
        assert checked.audio_gaps["segments"] == [0] and checked.status == MeetingJobStatus.COMPLETE
        broken = await store.get_meeting(bad.id)
        assert broken.status == MeetingJobStatus.COMPLETE and broken.audio_gaps["spans"] == [] and broken.audio_gaps["error"]

    asyncio.run(run())
