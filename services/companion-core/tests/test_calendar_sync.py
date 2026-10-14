"""ADR 0035 addendum: immediate synchronisation after a change of source. An uploaded ICS file (or a new link, or a manual refresh) is validated whole, then published atomically as
one new revision; an older refresh can never overwrite a newer source; a bad file changes nothing but the recorded error; an empty calendar is a valid snapshot. The acceptance
cases of the Calendar-screen request are the first tests here, and each one is checked through the revision the Web and Android screens both read (`schedule`)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from companion_core.calendar.classify import ClassificationRules
from companion_core.calendar.feed import (
    CalendarFeedService,
    FeedCalendar,
    FeedConfig,
    InMemoryFeedStore,
)
from companion_core.calendar.ics import FeedError
from companion_core.calendar.safe_fetch import FetchResult
from companion_core.calendar.store import InMemoryCalendarStore

FIXTURE = (Path(__file__).parent / "fixtures" / "calendar" / "work-calendar.ics").read_bytes()
URL = "https://calendar.example.com/private/abcdef-secret-token/basic.ics"
NOW = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)  # Monday 09:00 in Singapore
DAY = (datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC))


def ev(uid, start, end, summary, *extra, date=False):
    fmt = "%Y%m%d" if date else "%Y%m%dT%H%M%SZ"
    kind = ";VALUE=DATE" if date else ""
    lines = ["BEGIN:VEVENT", f"UID:{uid}@sync", "DTSTAMP:20261001T000000Z", f"DTSTART{kind}:{start:{fmt}}", f"DTEND{kind}:{end:{fmt}}"]
    if summary:
        lines.append(f"SUMMARY:{summary}")
    return "\n".join([*lines, *extra, "END:VEVENT"])


PEOPLE = ("ATTENDEE:mailto:owner@example.com", "ATTENDEE:mailto:dev@example.com")


def cal(*events) -> bytes:
    return ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\n" + "\n".join(events) + "\nEND:VCALENDAR\n").encode()


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def five():
    return cal(
        ev("a", at(13, 2), at(13, 3), "Design review", *PEOPLE), ev("b", at(13, 5), at(13, 6), "Vendor call", "LOCATION:https://zoom.us/j/1"),
        ev("c", at(14, 2), at(14, 3), "Sprint planning", *PEOPLE), ev("d", at(14, 6), at(14, 7), "Dentist appointment"), ev("e", at(15, 2), at(15, 3), "Retro", *PEOPLE),
    )


class Fetcher:
    def __init__(self, body=FIXTURE):
        self.body, self.error, self.fetched, self.gate = body, None, 0, None

    async def check(self, url):
        return "calendar.example.com"

    async def fetch(self, url):
        self.fetched += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.error:
            raise FeedError(self.error)
        return FetchResult(self.body)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def make(**config):
    fetcher, clock = Fetcher(), Clock()
    store = InMemoryFeedStore()
    service = CalendarFeedService(store, fetcher, clock=clock)
    asyncio.run(service.set_config(FeedConfig(rules=ClassificationRules(owner_emails=["owner@example.com"]), device_horizon_hours=168, **config)))
    return service, fetcher, clock, store


def run(coro):
    return asyncio.run(coro)


def titles(service, *, include_hidden=True):
    return sorted(e.title for e in run(service.events(*DAY)))


def reminders(service, hours=168):
    return {r["title"]: r for r in run(service.reminders(NOW, hours=hours))["reminders"]}


# --- the acceptance cases ---------------------------------------------------------------------------------------------------------------------------------------

def test_1_an_uploaded_file_shows_all_its_events_at_once_without_any_polling():
    service, fetcher, _clock, _ = make()
    status = run(service.upload(five(), "week.ics"))
    assert titles(service) == ["Dentist appointment", "Design review", "Retro", "Sprint planning", "Vendor call"] and status["event_count"] == 5
    assert fetcher.fetched == 0 and status["source"] == "upload" and status["host"] == "week.ics" and status["freshness"] == "fresh" and status["sync_state"] == "ok"
    assert set(reminders(service)) == {"Design review", "Vendor call", "Sprint planning", "Retro"}  # the dentist is not a meeting


def test_2_replacing_it_with_three_events_removes_the_other_two_and_their_reminders():
    service, _f, _c, _ = make()
    first = run(service.upload(five()))
    second = run(service.upload(cal(ev("a", at(13, 2), at(13, 3), "Design review", *PEOPLE), ev("c", at(14, 2), at(14, 3), "Sprint planning", *PEOPLE), ev("d", at(14, 6), at(14, 7), "Dentist appointment"))))
    assert titles(service) == ["Dentist appointment", "Design review", "Sprint planning"] and second["event_count"] == 3
    assert set(reminders(service)) == {"Design review", "Sprint planning"}
    assert second["generation"] == first["generation"] + 1 and second["snapshot_revision"] != first["snapshot_revision"]


def test_3_moving_a_meeting_from_10_to_11_reschedules_its_reminder_and_keeps_its_identity():
    service, _f, _c, _ = make()
    run(service.upload(cal(ev("m", at(13, 2), at(13, 3), "Standup", *PEOPLE))))  # 10:00 in Singapore
    before = reminders(service)["Standup"]
    run(service.upload(cal(ev("m", at(13, 3), at(13, 4), "Standup", "SEQUENCE:1", *PEOPLE))))
    after = reminders(service)["Standup"]
    assert after["event_key"] == before["event_key"] and after["start"] == before["start"] + timedelta(hours=1) and after["notify_at"] == before["notify_at"] + timedelta(hours=1)
    assert after["revision"] != before["revision"]


def test_4_cancelling_a_meeting_cancels_its_reminder_and_hides_the_event():
    service, _f, _c, _ = make()
    run(service.upload(five()))
    run(service.upload(five().replace(b"SUMMARY:Vendor call", b"SUMMARY:Vendor call\nSTATUS:CANCELLED")))
    assert "Vendor call" not in reminders(service) and "Vendor call" not in titles(service)
    assert "Vendor call" in {e.title for e in run(service.events(*DAY, include_cancelled=True))}


def test_5_a_malformed_file_keeps_the_last_valid_snapshot_and_records_the_error():
    service, _f, _c, _ = make()
    good = run(service.upload(five()))
    for bad in (b"BEGIN:VCALENDAR\nthis is broken secret-token-123", b"<html>not a calendar</html>", b"\xff\xfe\x00 binary", b""):
        with pytest.raises(FeedError):
            run(service.upload(bad))
    status = run(service.status())
    assert status["error"] == "not_calendar" and status["sync_state"] == "error" and status["consecutive_failures"] == 4
    assert titles(service) == ["Dentist appointment", "Design review", "Retro", "Sprint planning", "Vendor call"]  # still available
    assert status["generation"] == good["generation"] and status["snapshot_revision"] == good["snapshot_revision"] and status["host"] == good["host"]
    assert len(reminders(service)) == 4
    ok = run(service.upload(five()))  # a good file clears the error
    assert ok["error"] is None and ok["consecutive_failures"] == 0


def test_6_a_valid_empty_calendar_is_an_intentional_empty_snapshot_not_a_failure():
    service, _f, _c, _ = make()
    before = run(service.upload(five()))
    after = run(service.upload(cal()))
    assert after["error"] is None and after["sync_state"] == "ok" and after["event_count"] == 0 and after["freshness"] == "fresh"
    assert titles(service) == [] and reminders(service) == {} and after["generation"] == before["generation"] + 1
    assert run(service.reminders(NOW))["reminders"] == []  # the phone is told to cancel everything it had armed


def test_7_multi_day_leave_is_shown_over_its_days_and_never_gets_a_reminder():
    service, _f, _c, _ = make()
    run(service.upload(cal(ev("l", at(19, 0), at(22, 0), "Annual leave", date=True), ev("m", at(20, 6), at(20, 7), "Incident review", *PEOPLE))))
    leave = next(e for e in run(service.events(*DAY)) if e.title == "Annual leave")
    assert leave.classification == "leave_or_ooo" and leave.all_day and (leave.end - leave.start).days == 3 and leave.remind is False
    soon = {r["title"] for r in run(service.reminders(datetime(2026, 10, 19, tzinfo=UTC), hours=168))["reminders"]}
    assert "Annual leave" not in soon and "Incident review" in soon  # a meeting on a leave day is still reminded unless the owner says otherwise
    on = lambda d: [e.title for e in run(service.events(datetime(2026, 10, d, tzinfo=UTC), datetime(2026, 10, d + 1, tzinfo=UTC))) if e.classification == "leave_or_ooo"]
    assert on(19) == on(20) == on(21) == ["Annual leave"] and on(22) == []


def test_8_busy_only_entries_show_their_time_and_nothing_else():
    service, _f, _c, _ = make()
    run(service.upload(cal(
        ev("p", at(13, 2), at(13, 3), "Secret hospital visit", "CLASS:PRIVATE", "LOCATION:Ward 7", "DESCRIPTION:diagnosis details", "ATTENDEE:mailto:doctor@example.com"),
        ev("b", at(13, 5), at(13, 6), "Busy"),
    )))
    events = run(service.events(*DAY))
    assert [e.title for e in events] == ["Busy", "Busy"] and all(e.redacted and e.location is None and e.classification == "busy_private" for e in events)
    assert [(e.start, e.end) for e in events] == [(at(13, 2), at(13, 3)), (at(13, 5), at(13, 6))]
    blob = json.dumps(run(service.reminders(NOW)), default=str) + json.dumps([e.model_dump(mode="json") for e in events]) + json.dumps(run(service.status()), default=str)
    for secret in ("Secret hospital", "Ward 7", "diagnosis", "doctor@example.com"):
        assert secret not in blob
    assert run(service.reminders(NOW))["reminders"] == []  # hidden entries never get a reminder


def test_9_web_and_phone_read_one_revision():
    service, _f, _c, _ = make()
    calendar = FeedCalendar(InMemoryCalendarStore(), service)
    run(service.upload(five()))
    view = run(calendar.schedule(*DAY))
    phone = run(service.reminders(NOW))
    status = run(service.status())
    assert view["generation"] == view["feed"]["generation"] == phone["feed"]["generation"] == status["generation"]
    assert view["snapshot_revision"] == phone["snapshot_revision"] == phone["feed"]["snapshot_revision"] == status["snapshot_revision"]
    assert [e.start for e in view["events"]] == sorted(e.start for e in view["events"])  # chronological
    run(service.upload(cal(ev("z", at(16, 2), at(16, 3), "Only one", *PEOPLE))))
    again = run(calendar.schedule(*DAY))
    assert again["generation"] == view["generation"] + 1 and [e.title for e in again["events"]] == ["Only one"] and run(service.reminders(NOW))["snapshot_revision"] == again["snapshot_revision"]


# --- 10: restart, duplicates, concurrency, network failure ------------------------------------------------------------------------------------------------------

def test_10a_a_restart_sees_the_same_revision_and_events():
    service, fetcher, clock, store = make()
    run(service.upload(five(), "week.ics"))
    restarted = CalendarFeedService(store, fetcher, clock=clock)
    assert run(restarted.status())["generation"] == run(service.status())["generation"] and titles(restarted) == titles(service)
    assert run(restarted.reminders(NOW))["reminders"] == run(service.reminders(NOW))["reminders"]
    run(restarted.refresh())  # the stored upload is re-read: no download, same revision
    assert fetcher.fetched == 0 and run(restarted.status())["generation"] == run(service.status())["generation"]


def test_10b_the_same_upload_twice_is_one_revision():
    service, _f, _c, _ = make()
    first = run(service.upload(five()))
    again = run(service.upload(five()))
    assert again["generation"] == first["generation"] and again["snapshot_revision"] == first["snapshot_revision"] and len(titles(service)) == 5
    assert len({r["event_key"] for r in run(service.reminders(NOW))["reminders"]}) == len(run(service.reminders(NOW))["reminders"])  # nothing doubled


def test_10c_identical_concurrent_uploads_share_one_parse_and_different_ones_end_on_the_last():
    service, _f, _c, _ = make()
    from companion_core.calendar import feed

    calls = []
    real = feed.parse_feed
    feed.parse_feed = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    try:
        async def go():
            return await asyncio.gather(*[service.upload(five()) for _ in range(6)])
        results = run(go())
    finally:
        feed.parse_feed = real
    assert len(calls) == 1 and len({r["generation"] for r in results}) == 1 and len(titles(service)) == 5
    a, b = cal(ev("x", at(13, 2), at(13, 3), "First", *PEOPLE)), cal(ev("y", at(13, 2), at(13, 3), "Second", *PEOPLE))

    async def race():
        await asyncio.gather(service.upload(a), service.upload(b))
    run(race())
    assert titles(service) in (["First"], ["Second"])  # one whole calendar, never a mixture of the two


def test_10d_an_older_refresh_cannot_overwrite_a_newer_upload():
    service, fetcher, _clock, _ = make()
    run(service.set_url(URL))  # source: the link, with the fixture calendar

    async def go():
        fetcher.gate = asyncio.Event()
        refreshing = asyncio.ensure_future(service.refresh())  # started under the old source, blocked in its download
        await asyncio.sleep(0.05)
        uploaded = await service.upload(cal(ev("u", at(16, 2), at(16, 3), "Uploaded meeting", *PEOPLE)), "mine.ics")
        fetcher.gate.set()
        await refreshing
        return uploaded
    uploaded = run(go())
    status = run(service.status())
    assert titles(service) == ["Uploaded meeting"] and status["source"] == "upload" and status["generation"] == uploaded["generation"]
    assert run(service._store.get_url()).startswith("BEGIN:VCALENDAR")  # the stored source is the upload, not the link the old refresh was fetching


def test_10e_concurrent_refreshes_share_one_download():
    service, fetcher, _clock, _ = make()
    run(service.set_url(URL))
    fetched = fetcher.fetched

    async def go():
        fetcher.gate = asyncio.Event()
        runs = [asyncio.ensure_future(service.refresh()) for _ in range(5)]
        await asyncio.sleep(0.05)
        assert service._brief(await service._load(), NOW)["sync_state"] == "refreshing"  # visible to the screens while it runs
        fetcher.gate.set()
        return await asyncio.gather(*runs)
    results = run(go())
    assert fetcher.fetched == fetched + 1 and len({r["generation"] for r in results}) == 1


def test_10f_a_temporary_network_failure_keeps_everything_and_recovery_does_not_move_the_revision():
    service, fetcher, clock, _ = make()
    run(service.set_url(URL))
    good = run(service.status())
    before = reminders(service)
    fetcher.error = "timeout"
    for _ in range(3):
        clock.now += timedelta(minutes=15)
        run(service.refresh())
    down = run(service.status())
    assert down["error"] == "timeout" and down["sync_state"] == "error" and down["consecutive_failures"] == 3 and down["generation"] == good["generation"]
    assert down["last_success_at"] == good["last_success_at"] and down["last_attempt_at"] > good["last_attempt_at"]  # last good refresh and last attempt are separate facts
    assert reminders(service) == before
    fetcher.error = None
    up = run(service.refresh())
    assert up["error"] is None and up["generation"] == good["generation"] and up["last_success_at"] > good["last_success_at"]  # same calendar: the revision did not move


def test_a_changed_link_that_does_not_work_changes_nothing_and_an_unchanged_calendar_keeps_its_revision():
    service, fetcher, _clock, _ = make()
    good = run(service.set_url(URL))
    fetcher.error = "http_404"
    with pytest.raises(FeedError):
        run(service.set_url(URL.replace("abcdef", "ghijkl")))
    now = run(service.status())
    assert now["generation"] == good["generation"] and "ghijkl" not in run(service._store.get_url()) and titles(service)
    fetcher.error = None
    assert run(service.refresh())["generation"] == good["generation"]  # identical content: not a new revision


def test_a_rule_or_override_change_is_a_new_revision_so_every_client_rereads():
    service, _f, _c, _ = make()
    before = run(service.upload(five()))
    key = next(e.event_key for e in run(service.events(*DAY)) if e.title == "Dentist appointment")
    after = run(service.set_override(key, "meeting"))
    assert after["generation"] == before["generation"] + 1 and "Dentist appointment" in reminders(service)


def test_switching_between_link_and_upload_replaces_the_source_and_clear_keeps_the_revision_moving():
    service, fetcher, _c, _ = make()
    run(service.set_url(URL))
    up = run(service.upload(five(), r"C:\Users\me\week.ics"))
    assert up["host"] == "week.ics" and up["source"] == "upload"  # only the file's name, never a path
    fetched = fetcher.fetched
    run(service.refresh())
    assert fetcher.fetched == fetched  # the link is no longer the source
    cleared = run(service.clear())
    assert cleared["configured"] is False and cleared["generation"] > up["generation"] and run(service.reminders(NOW))["reminders"] == []


def test_the_uploaded_text_and_the_link_are_not_in_status_logs_or_repr(caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    service, _fetcher, _c, _ = make()
    run(service.set_url(URL))
    with pytest.raises(FeedError):
        run(service.upload(b"BEGIN:VCALENDAR\nsecret-token-in-a-broken-upload"))
    run(service.upload(cal(ev("s", at(13, 2), at(13, 3), "Quarterly numbers", "DESCRIPTION:confidential agenda text", *PEOPLE))))
    everything = json.dumps(run(service.status()), default=str) + caplog.text + repr(service) + repr(run(service._load()))
    assert "secret-token" not in everything and "confidential agenda" not in everything and "abcdef" not in everything
    assert "Quarterly numbers" not in caplog.text  # titles are never logged
