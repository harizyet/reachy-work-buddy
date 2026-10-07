"""Phase 27.4: aligning the transcript with the speakers, and the job completing."""

import asyncio

from companion_core.meetings.align import MAX_GAP_S, align
from companion_core.meetings.models import MeetingJobStatus
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.meetings.worker import MeetingWorker


def seg(start, end, text="x"):
    return {"start": start, "end": end, "text": text}


def spk(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker}


def speakers(transcript, spans):
    return [s["speaker"] for s in align(transcript, spans)]


def test_each_segment_takes_the_speaker_with_the_most_overlap() -> None:
    spans = [spk(0, 5, "A"), spk(5, 12, "B")]
    assert speakers([seg(0, 4), seg(4.5, 11), seg(6, 10)], spans) == ["A", "B", "B"]


def test_a_speakers_several_short_spans_add_up() -> None:
    spans = [spk(0, 2, "A"), spk(2, 5, "B"), spk(5, 7, "A"), spk(7, 8, "B")]  # A: 4s, B: 4s... tip it
    spans[3] = spk(7, 7.5, "B")  # A 4.0s vs B 3.5s inside 0-8
    assert speakers([seg(0, 8)], spans) == ["A"]


def test_a_segment_in_a_gap_takes_the_nearest_speaker_only_when_close() -> None:
    spans = [spk(0, 5, "A"), spk(10, 15, "B")]
    assert speakers([seg(5.5, 6.0)], spans) == ["A"]  # 0.5 s after A
    assert speakers([seg(9.2, 9.8)], spans) == ["B"]  # 0.2 s before B
    assert speakers([seg(7.0, 7.5)], spans) == [None]  # more than MAX_GAP_S from anyone
    assert MAX_GAP_S >= 1.0


def test_no_diarization_leaves_speakers_empty_and_the_text_is_kept() -> None:
    for spans in (None, [], [{"start": 0, "end": 3}]):  # spans without a speaker label are ignored
        out = align([seg(0, 3, " hello ")], spans)
        assert out == [{"start": 0.0, "end": 3.0, "text": "hello", "speaker": None}]


def test_the_result_is_index_aligned_with_the_transcript() -> None:
    transcript = [seg(0, 1, "a"), seg(1, 2, ""), seg(2, 3, "c")]
    out = align(transcript, [spk(0, 3, "A")])
    assert len(out) == 3 and [s["text"] for s in out] == ["a", "", "c"]  # empty text kept so indexes never shift


def test_an_instant_segment_belongs_to_whoever_is_speaking() -> None:
    assert speakers([seg(5, 5)], [spk(0, 4, "A"), spk(4, 9, "B")]) == ["B"]


def test_bad_or_reversed_times_do_not_crash() -> None:
    assert speakers([seg(5, 3)], [spk(0, 10, "A")]) == ["A"]
    assert speakers([{"text": "no times"}], [spk(0, 1, "A")]) == ["A"]


# ---- the worker stage ----------------------------------------------------------------------------------------------

def make_aligning(store, transcript, spans):
    async def go():
        m = await store.create_meeting(title="t", audio=b"x", source_filename="m.wav", content_type="audio/wav")
        store._touch(m, status=MeetingJobStatus.ALIGNING, transcript_segments=transcript, diarization_segments=spans)
        return m.id

    return asyncio.run(go())


def test_the_worker_aligns_stores_the_result_and_completes_the_meeting() -> None:
    store = InMemoryMeetingStore()
    mid = make_aligning(store, [seg(0, 4, "hello"), seg(5, 9, "hi")], [spk(0, 5, "SPEAKER_00"), spk(5, 10, "SPEAKER_01")])

    async def run():
        worker = MeetingWorker(store)
        assert await worker.process_one() is True
        meeting = await store.get_meeting(mid)
        assert meeting.status == MeetingJobStatus.COMPLETE
        assert [s["speaker"] for s in meeting.aligned_segments] == ["SPEAKER_00", "SPEAKER_01"]
        assert meeting.transcript_segments[0]["text"] == "hello"  # raw evidence untouched
        assert await worker.process_one() is False  # nothing left to do

    asyncio.run(run())


def test_mark_aligned_only_acts_on_a_meeting_that_is_still_aligning() -> None:
    store = InMemoryMeetingStore()
    mid = make_aligning(store, [seg(0, 1)], [])

    async def run():
        await store.mark_aligned(mid, aligned_segments=[{"speaker": "A"}])
        later = await store.mark_aligned(mid, aligned_segments=[{"speaker": "OVERWRITE"}])
        assert later.aligned_segments == [{"speaker": "A"}]  # a second call changes nothing
        assert await store.mark_aligned("missing", aligned_segments=[]) is None

    asyncio.run(run())


def test_a_crash_in_alignment_fails_the_job_not_the_worker(monkeypatch) -> None:
    import companion_core.meetings.worker as worker_module

    store = InMemoryMeetingStore()
    mid = make_aligning(store, [seg(0, 1)], [])
    monkeypatch.setattr(worker_module, "align", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    async def run():
        assert await MeetingWorker(store).process_one() is True
        meeting = await store.get_meeting(mid)
        assert meeting.status == MeetingJobStatus.FAILED and "alignment error: boom" in meeting.error_detail

    asyncio.run(run())


def test_meetings_that_were_already_resting_at_aligning_are_completed_on_the_next_poll() -> None:
    """Meetings processed before alignment existed sit at ALIGNING; the worker picks them up with no migration of data."""
    store = InMemoryMeetingStore()
    ids = [make_aligning(store, [seg(0, 2, f"m{n}")], [spk(0, 2, "SPEAKER_00")]) for n in range(3)]

    async def run():
        worker = MeetingWorker(store)
        while await worker.process_one():
            pass
        assert [(await store.get_meeting(i)).status for i in ids] == [MeetingJobStatus.COMPLETE] * 3

    asyncio.run(run())
