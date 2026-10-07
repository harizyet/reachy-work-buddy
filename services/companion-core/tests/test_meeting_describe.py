"""Automatic meeting titles and descriptions: parsing, the worker stage, and who named the meeting."""

import asyncio

from companion_core.meetings import describe
from companion_core.meetings.models import MeetingJobStatus
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.meetings.worker import DESCRIBE_RETRY_SECONDS, MeetingWorker


def test_parse_reads_the_two_lines_and_tidies_them() -> None:
    parsed = describe.parse('TITLE: "ClickHouse vs InfluxDB."\nDESCRIPTION:  The team compared   two databases.\n')
    assert parsed == describe.Described("ClickHouse vs InfluxDB", "The team compared two databases.")
    assert describe.parse("**Title:** Weekly sync\n**Description:** Status round.") == describe.Described("Weekly sync", "Status round.")
    assert describe.parse("I cannot say.") == describe.Described(None, "")
    assert describe.parse("TITLE: " + "x" * 300).title == "x" * describe.TITLE_MAX
    assert describe.parse("TITLE: First\nTITLE: Second\nDESCRIPTION: a").title == "First"


def test_only_the_apps_own_default_names_count_as_unnamed() -> None:
    for default in ("Meeting 7 Oct 12:05", "Meeting 7 Oct 12:05 ", "Recording", "", "  "):
        assert describe.looks_default(default), default
    for chosen in ("Weekly sync", "Meeting with Priya about the budget review", "Q3 planning"):
        assert not describe.looks_default(chosen), chosen


def test_a_long_transcript_is_sampled_across_its_whole_length() -> None:
    lines = [f"[0:{i:02d}] line number {i} " + "x" * 40 for i in range(400)]
    picked = describe.sample_lines(lines, budget=2000)
    assert 10 < len(picked) < 60 and picked[0] == lines[0] and sum(len(x) + 1 for x in picked) <= 2100
    assert any(int(x.split("line number ")[1].split()[0]) > 300 for x in picked)   # the end is represented too
    assert describe.sample_lines(lines[:3]) == lines[:3]


def _complete(store, title: str, segments=None):
    async def make():
        m = await store.create_meeting(title=title, audio=b"x", source_filename="m.m4a", content_type="audio/mp4")
        store._touch(m, status=MeetingJobStatus.COMPLETE, transcript_segments=segments or [{"start": 0, "end": 3, "text": "budget review"}], audio_gaps={"spans": [], "segments": []})
        return m.id

    return asyncio.run(make())


def test_the_worker_names_an_unnamed_meeting_and_keeps_an_owner_title() -> None:
    store = InMemoryMeetingStore()
    unnamed = _complete(store, "Meeting 7 Oct 12:05")
    chosen = _complete(store, "Q3 planning")

    async def describer(meeting):
        return describe.Described("Budget Review", f"About the budget ({meeting.title}).")

    async def run():
        assert (await store.get_meeting(unnamed)).title_source == "default"
        assert (await store.get_meeting(chosen)).title_source == "owner"
        worker = MeetingWorker(store, describer=describer)
        assert await worker.process_one() is True and await worker.process_one() is True
        assert await worker.process_one() is False
        a, b = await store.get_meeting(unnamed), await store.get_meeting(chosen)
        assert (a.title, a.title_source, a.description) == ("Budget Review", "generated", "About the budget (Meeting 7 Oct 12:05).")
        assert (b.title, b.title_source) == ("Q3 planning", "owner") and b.description == "About the budget (Q3 planning)."

    asyncio.run(run())


def test_an_unreachable_model_is_retried_later_and_a_bad_reply_is_not_retried_forever() -> None:
    store = InMemoryMeetingStore()
    mid = _complete(store, "Meeting 7 Oct 12:05")
    calls = []
    answers = [None, describe.Described(None, "")]

    async def describer(meeting):
        calls.append(1)
        return answers.pop(0)

    async def run():
        worker = MeetingWorker(store, describer=describer)
        assert await worker.process_one() is False and len(calls) == 1          # model down: nothing done
        assert await worker.process_one() is False and len(calls) == 1          # and not asked again straight away
        worker._describe_retry_at = 0.0
        assert await worker.process_one() is True and len(calls) == 2
        done = await store.get_meeting(mid)
        assert done.description == "" and done.title == "Meeting 7 Oct 12:05"   # nothing usable: kept, and settled
        assert await worker.process_one() is False and len(calls) == 2
        assert DESCRIBE_RETRY_SECONDS >= 60

    asyncio.run(run())


def test_without_a_describer_the_worker_leaves_titles_alone() -> None:
    store = InMemoryMeetingStore()
    _complete(store, "Meeting 7 Oct 12:05")

    async def run():
        assert await MeetingWorker(store).process_one() is False

    asyncio.run(run())
