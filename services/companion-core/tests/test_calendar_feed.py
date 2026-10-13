"""ADR 0035: the feed service. A fake fetcher serves bytes from the fixtures, a mutable clock stands in for time, and the store is the in-memory one. What is pinned here: the URL is
never returned or logged, a failed refresh keeps the last good snapshot and says how old it is, reminders follow the calendar when it changes and keep one identity per occurrence,
and the owner's overrides and rules apply at read time."""

import asyncio
import json
import logging
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
from companion_core.calendar.models import CalendarEvent
from companion_core.calendar.safe_fetch import FetchResult
from companion_core.calendar.store import InMemoryCalendarStore

FIXTURE = (Path(__file__).parent / "fixtures" / "calendar" / "work-calendar.ics").read_bytes()
URL = "https://calendar.example.com/private/abcdef-secret-token/basic.ics"
NOW = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)  # Monday 09:00 in Singapore
RULES = ClassificationRules(owner_emails=["owner@example.com"])


class FakeFetcher:
    def __init__(self, body: bytes = FIXTURE):
        self.body, self.error, self.fetched, self.checked = body, None, 0, []

    async def check(self, url):
        self.checked.append(url)
        if "unsafe" in url:
            raise FeedError("unsafe_address")
        return "calendar.example.com"

    async def fetch(self, url):
        self.fetched += 1
        if self.error:
            raise FeedError(self.error)
        return FetchResult(self.body)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def make(body=FIXTURE, **config):
    fetcher, clock = FakeFetcher(body), Clock()
    async def zone():
        return "Asia/Singapore"
    service = CalendarFeedService(InMemoryFeedStore(), fetcher, clock=clock, timezone=zone)
    asyncio.run(service.set_config(FeedConfig(rules=RULES, **{"device_horizon_hours": 168, **config})))
    return service, fetcher, clock


def run(coro):
    return asyncio.run(coro)


def configured(**kw):
    service, fetcher, clock = make(**kw)
    run(service.set_url(URL))
    run(service.refresh())
    return service, fetcher, clock


def keys(payload):
    return [r["event_key"] for r in payload["reminders"]]


def titles(payload):
    return {r["title"] for r in payload["reminders"]}


# --- the secret -------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_url_is_never_returned_logged_or_in_a_repr(caplog):
    caplog.set_level(logging.DEBUG)
    service, fetcher, _clock = make()
    status = run(service.set_url(URL))
    fetcher.error = "http_404"
    failed = run(service.refresh())
    fetcher.error = None
    run(service.refresh())
    everything = json.dumps([status, failed, run(service.status()), run(service.reminders(NOW))], default=str) + caplog.text + repr(service) + repr(run(service._load()))
    assert "secret-token" not in everything and "abcdef" not in everything and "/private/" not in everything
    assert run(service.status())["host"] == "calendar.example.com"  # the host is shown so the owner can see which feed is set; the path is the secret


def test_an_unsafe_url_is_refused_and_nothing_is_stored():
    service, _fetcher, _clock = make()
    with pytest.raises(FeedError) as caught:
        run(service.set_url("https://unsafe.example.com/x.ics"))
    assert caught.value.code == "unsafe_address"
    assert run(service.status())["configured"] is False and run(service._store.get_url()) is None


def test_clearing_forgets_the_url_and_the_snapshot_but_keeps_the_settings():
    service, _fetcher, _clock = configured(lead_minutes=9)
    run(service.set_override("ics:abc", "meeting"))
    status = run(service.clear())
    assert status["configured"] is False and status["event_count"] == 0 and status["config"]["lead_minutes"] == 9 and status["overrides"] == {"ics:abc": "meeting"}
    assert run(service._store.get_url()) is None and run(service.reminders(NOW))["reminders"] == []


# --- refresh, freshness, failure --------------------------------------------------------------------------------------------------------------------------------

def test_refresh_stores_a_snapshot_and_reports_fresh():
    service, _fetcher, _clock = configured()
    status = run(service.status())
    assert status["freshness"] == "fresh" and status["event_count"] > 15 and status["error"] is None and status["age_seconds"] == 0


def test_a_failed_refresh_keeps_the_last_good_snapshot_and_records_the_code():
    service, fetcher, clock = configured()
    before = keys(run(service.reminders(NOW)))
    fetcher.error = "http_503"
    clock.now += timedelta(minutes=20)
    status = run(service.refresh())
    assert status["error"] == "http_503" and status["consecutive_failures"] == 1 and status["event_count"] > 15
    assert keys(run(service.reminders(NOW))) == before  # the schedule does not vanish because the feed was down
    run(service.refresh())
    assert run(service.status())["consecutive_failures"] == 2


def test_freshness_turns_stale_with_age_and_recovers():
    service, fetcher, clock = configured()  # refresh every 15 minutes: stale after 2 intervals and 5 minutes of grace
    fetcher.error = "timeout"
    clock.now += timedelta(minutes=34)
    assert run(service.status())["freshness"] == "fresh"
    clock.now += timedelta(minutes=2)
    assert run(service.status())["freshness"] == "stale"
    fetcher.error = None
    run(service.refresh())
    status = run(service.status())
    assert status["freshness"] == "fresh" and status["error"] is None and status["consecutive_failures"] == 0


def test_a_link_is_stored_only_once_it_has_been_downloaded_and_validated():
    service, fetcher, _clock = make()
    assert run(service.status())["freshness"] == "not_configured"
    fetcher.error = "http_404"
    with pytest.raises(FeedError):
        run(service.set_url(URL))
    status = run(service.status())
    assert status["configured"] is False and status["error"] == "http_404" and run(service._store.get_url()) is None  # a link that does not work changes nothing
    fetcher.error = None
    assert run(service.set_url(URL))["freshness"] == "fresh"


def test_refresh_runs_on_the_configured_interval_only():
    service, fetcher, clock = make(refresh_minutes=30)
    run(service.set_url(URL))  # downloads and publishes at once
    assert fetcher.fetched == 1
    clock.now += timedelta(minutes=29)
    assert run(service.refresh_if_due()) is False and fetcher.fetched == 1
    clock.now += timedelta(minutes=2)
    assert run(service.refresh_if_due()) is True and fetcher.fetched == 2


def test_a_failed_attempt_also_waits_a_full_interval():
    service, fetcher, clock = make(refresh_minutes=15)
    run(service.set_url(URL))
    fetcher.error = "timeout"
    run(service.refresh_if_due())
    clock.now += timedelta(minutes=5)
    assert run(service.refresh_if_due()) is False


def test_nothing_is_fetched_without_a_url():
    service, fetcher, _clock = make()
    assert run(service.refresh_if_due()) is False and run(service.refresh())["configured"] is False and fetcher.fetched == 0


def test_a_calendar_that_stops_being_a_calendar_is_a_failure_not_an_empty_calendar():
    service, fetcher, _clock = configured()
    fetcher.body = b"BEGIN:VCALENDAR\nthis is broken secret-token"
    status = run(service.refresh())
    assert status["error"] == "not_calendar" and status["event_count"] > 15


# --- reminders --------------------------------------------------------------------------------------------------------------------------------------------------

def test_default_reminder_is_five_minutes_before_and_only_for_meetings():
    service, _fetcher, _clock = configured(device_horizon_hours=72)
    payload = run(service.reminders(NOW))
    assert payload["lead_minutes"] == 5
    by_title = {r["title"]: r for r in payload["reminders"] if r["title"]}
    review = by_title["Design review"]
    assert review["start"] == datetime(2026, 10, 13, 6, 0, tzinfo=UTC) and review["notify_at"] == review["start"] - timedelta(minutes=5)
    assert {"Design review", "Vendor call", "Weekly sync"} <= set(by_title)
    # never: cancelled, declined, all-day, leave, personal, unknown, hidden
    assert not ({"Cancelled planning meeting", "Budget review", "Annual leave", "Dentist appointment", "Quiet time", "Away", "Team offsite", "Day off"} & set(by_title))
    assert all(r["classification"] == "meeting" for r in payload["reminders"])


def test_lead_time_is_configurable():
    service, _fetcher, _clock = configured(lead_minutes=15)
    review = next(r for r in run(service.reminders(NOW))["reminders"] if r["title"] == "Design review")
    assert review["lead_minutes"] == 15 and review["notify_at"] == review["start"] - timedelta(minutes=15)
    with pytest.raises(ValueError):
        FeedConfig(lead_minutes=0)
    with pytest.raises(ValueError):
        FeedConfig(timezone="Mars/Olympus")


def test_the_horizon_bounds_what_the_phone_is_given():
    service, _fetcher, _clock = configured(device_horizon_hours=24)
    payload = run(service.reminders(NOW))
    assert payload["horizon_end"] == NOW + timedelta(hours=24)
    assert titles(payload) == {"Weekly sync"}  # 24 hours from Monday 09:00 ends before Tuesday's 14:00 design review
    assert len(run(service.reminders(NOW, hours=6))["reminders"]) == 1  # a request can narrow the horizon, never widen it
    assert len(run(service.reminders(NOW, hours=500))["reminders"]) == len(run(service.reminders(NOW))["reminders"])  # asking for more than the setting gives the setting
    assert FeedConfig().device_horizon_hours == 72


def test_reminders_for_events_already_started_are_not_listed():
    service, _fetcher, _clock = configured()
    later = NOW + timedelta(hours=1)  # 10:00: the 09:30 weekly sync has started
    assert "Weekly sync" not in titles(run(service.reminders(later)))


def test_every_reminder_keeps_its_source_identity_and_keys_are_unique():
    service, _fetcher, _clock = configured()
    payload = run(service.reminders(NOW, hours=168))
    assert all(r["event_key"].startswith("ics:") and r["series_key"] in r["event_key"] for r in payload["reminders"])
    assert len(set(keys(payload))) == len(payload["reminders"])
    assert payload["snapshot_revision"] == run(service._load()).snapshot.revision


def test_identity_survives_refreshes_and_restarts():
    service, fetcher, clock = configured()
    first = run(service.reminders(NOW, hours=168))
    run(service.refresh())
    again = run(service.reminders(NOW, hours=168))
    restarted = CalendarFeedService(service._store, fetcher, clock=clock)  # a new process reads the stored state
    assert keys(first) == keys(again) == keys(run(restarted.reminders(NOW, hours=168)))
    assert first["snapshot_revision"] == again["snapshot_revision"]  # an unchanged calendar is an unchanged snapshot, so the phone has nothing to redo


def test_rescheduling_keeps_the_key_moves_the_time_and_changes_the_revision():
    service, fetcher, _clock = configured()
    before = next(r for r in run(service.reminders(NOW, hours=168))["reminders"] if r["title"] == "Design review")
    fetcher.body = (FIXTURE.replace(b"DTSTART;TZID=Asia/Singapore:20261013T140000", b"DTSTART;TZID=Asia/Singapore:20261013T160000")
                    .replace(b"DTEND;TZID=Asia/Singapore:20261013T150000", b"DTEND;TZID=Asia/Singapore:20261013T170000"))
    run(service.refresh())
    after = next(r for r in run(service.reminders(NOW, hours=168))["reminders"] if r["title"] == "Design review")
    assert after["event_key"] == before["event_key"] and after["revision"] != before["revision"]
    assert after["start"] == before["start"] + timedelta(hours=2) and after["notify_at"] == before["notify_at"] + timedelta(hours=2)


def test_a_cancelled_or_removed_meeting_disappears_from_the_reminders():
    service, fetcher, _clock = configured()
    key = next(r["event_key"] for r in run(service.reminders(NOW, hours=168))["reminders"] if r["title"] == "Vendor call")
    fetcher.body = FIXTURE.replace(b"SUMMARY:Vendor call", b"SUMMARY:Vendor call\nSTATUS:CANCELLED")
    run(service.refresh())
    assert key not in keys(run(service.reminders(NOW, hours=168)))
    fetcher.body = FIXTURE.replace(b"UID:vendor-call@fixture", b"UID:other@fixture").replace(b"SUMMARY:Vendor call", b"SUMMARY:Vendor call moved to a new invite")
    run(service.refresh())
    assert key not in keys(run(service.reminders(NOW, hours=168)))  # a new UID is a different event; the old one is gone


def test_a_moved_instance_of_a_series_keeps_the_instance_identity():
    service, fetcher, _clock = configured()
    at = datetime(2026, 10, 20, tzinfo=UTC)
    before = next(r for r in run(service.reminders(at, hours=168))["reminders"] if r["title"] == "Weekly sync (moved)")
    fetcher.body = FIXTURE.replace(b"DTSTART;TZID=Asia/Singapore:20261026T110000", b"DTSTART;TZID=Asia/Singapore:20261026T130000").replace(b"DTEND;TZID=Asia/Singapore:20261026T113000", b"DTEND;TZID=Asia/Singapore:20261026T133000")
    run(service.refresh())
    after = next(r for r in run(service.reminders(at, hours=168))["reminders"] if r["title"] == "Weekly sync (moved)")
    assert after["event_key"] == before["event_key"] and after["start"].hour == 13 and before["start"].hour == 11  # local (Singapore) times


def test_missing_and_hidden_titles_are_null_not_invented():
    service, _fetcher, _clock = configured()
    payload = run(service.reminders(NOW, hours=168))
    untitled = [r for r in payload["reminders"] if r["title"] is None]
    assert len(untitled) == 1 and untitled[0]["classification"] == "meeting"
    run(service.set_override(next(f.key for f in run(service._load()).snapshot.facts if f.redacted and f.source_uid == "private@fixture"), "meeting"))
    private = next(r for r in run(service.reminders(NOW - timedelta(hours=1), hours=168))["reminders"] if r["start"] == datetime(2026, 10, 12, 3, 0, tzinfo=UTC))
    assert private["title"] is None and private["basis"] == "owner"  # an override makes it a meeting; it does not unhide it
    assert "Secret hospital" not in json.dumps(run(service.reminders(NOW - timedelta(hours=1), hours=168)), default=str)


# --- overrides and rules apply at read time ---------------------------------------------------------------------------------------------------------------------

def test_override_by_occurrence_and_by_series():
    service, _fetcher, _clock = configured()
    facts = {f.title: f for f in run(service._load()).snapshot.facts if f.title}
    dentist = facts["Dentist appointment"]
    run(service.set_override(dentist.key, "meeting"))
    assert "Dentist appointment" in titles(run(service.reminders(NOW, hours=168)))
    run(service.set_override(facts["Weekly sync"].series_key, "unknown_timed"))
    assert "Weekly sync" not in titles(run(service.reminders(NOW, hours=168))) and "Weekly sync (moved)" not in titles(run(service.reminders(datetime(2026, 10, 20, tzinfo=UTC), hours=168)))
    run(service.set_override(facts["Weekly sync (moved)"].key, "meeting"))  # the occurrence beats the series
    assert "Weekly sync (moved)" in titles(run(service.reminders(datetime(2026, 10, 20, tzinfo=UTC), hours=168)))
    run(service.set_override(dentist.key, None))
    assert "Dentist appointment" not in titles(run(service.reminders(NOW, hours=168)))


def test_override_inputs_are_validated():
    service, _fetcher, _clock = configured()
    for bad in ("", "google:abc", "x" * 200, "meeting"):
        with pytest.raises(ValueError):
            run(service.set_override(bad, "meeting"))
    with pytest.raises(ValueError):
        run(service.set_override("ics:abc", "important"))


def test_overrides_survive_a_refresh_and_a_new_service_object():
    service, fetcher, clock = configured()
    run(service.set_override("ics:abc:0", "leave_or_ooo"))
    run(service.refresh())
    assert run(CalendarFeedService(service._store, fetcher, clock=clock).status())["overrides"] == {"ics:abc:0": "leave_or_ooo"}


def test_rules_change_the_result_without_a_new_download():
    service, fetcher, _clock = configured()
    at = datetime(2026, 10, 19, tzinfo=UTC)
    assert "Floating sync" in titles(run(service.reminders(at, hours=168)))
    run(service.set_config(FeedConfig(device_horizon_hours=168, rules=ClassificationRules(owner_emails=["owner@example.com"], remind_keyword_meetings=False))))
    assert "Floating sync" not in titles(run(service.reminders(at, hours=168))) and fetcher.fetched == 2  # set_url and the first refresh; the rule change downloaded nothing


def test_leave_suppression_is_off_by_default_and_works_when_on():
    service, _fetcher, _clock = configured()
    at = datetime(2026, 10, 19, tzinfo=UTC)
    assert "Incident review" in titles(run(service.reminders(at, hours=72)))
    run(service.set_config(FeedConfig(rules=ClassificationRules(owner_emails=["owner@example.com"], leave_suppresses_meetings=True))))
    assert "Incident review" not in titles(run(service.reminders(at, hours=72)))


# --- events as the API and the assistant read them --------------------------------------------------------------------------------------------------------------

def test_events_carry_classification_status_and_identity():
    service, _fetcher, _clock = configured()
    events = run(service.events(datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 17, tzinfo=UTC)))
    by_title = {e.title: e for e in events}
    assert by_title["Design review"].classification == "meeting" and by_title["Design review"].remind and by_title["Design review"].source == "ics"
    assert by_title["Dentist appointment"].classification == "personal_appointment" and by_title["Dentist appointment"].remind_blocked == "not_a_meeting:personal_appointment"
    assert by_title["Quiet time"].classification == "unknown_timed"
    assert by_title["Busy"].redacted and by_title["Busy"].classification == "busy_private" and by_title["Busy"].location is None
    assert "(untitled event)" in by_title and by_title["(untitled event)"].title_missing
    assert "Cancelled planning meeting" not in by_title  # cancelled events are not listed unless asked for
    assert by_title["Budget review"].response == "declined"
    assert all(e.event_key and e.series_key for e in events)
    with_cancelled = run(service.events(datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 17, tzinfo=UTC), include_cancelled=True))
    assert {e.title: e for e in with_cancelled}["Cancelled planning meeting"].status == "cancelled"


def test_multi_day_leave_overlaps_the_days_it_covers_and_not_the_exclusive_end():
    service, _fetcher, _clock = configured()
    def leave(day_start, day_end):
        return [e.title for e in run(service.events(day_start, day_end)) if e.classification == "leave_or_ooo"]
    sgt = lambda d, h=0: datetime(2026, 10, d, h, tzinfo=UTC) - timedelta(hours=8)
    assert leave(sgt(19), sgt(20)) == ["Annual leave"] and leave(sgt(21), sgt(22)) == ["Annual leave"]
    assert leave(sgt(22), sgt(23)) == []  # the end date is exclusive
    assert leave(sgt(18), sgt(19)) == []


# --- the calendar store the rest of the service sees --------------------------------------------------------------------------------------------------------------

def test_feed_calendar_merges_classifies_local_events_and_keeps_writes_local():
    service, _fetcher, _clock = configured()
    inner = InMemoryCalendarStore()
    calendar = FeedCalendar(inner, service)
    local = CalendarEvent(title="Team standup", start=datetime(2026, 10, 12, 2, 0, tzinfo=UTC), end=datetime(2026, 10, 12, 2, 15, tzinfo=UTC))
    run(calendar.add_event(local))
    events = run(calendar.list_events(datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 13, tzinfo=UTC)))
    by_title = {e.title: e for e in events}
    assert by_title["Team standup"].source == "local" and by_title["Team standup"].classification == "meeting"  # a local event is classified too (title rule), not left blank
    assert by_title["Weekly sync"].source == "ics"
    assert [e.start for e in events] == sorted(e.start for e in events)
    assert run(inner.list_events(datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 13, tzinfo=UTC))) == [local]  # the feed never wrote to the inner store


def test_next_event_skips_all_day_and_leave():
    service, _fetcher, _clock = configured()
    calendar = FeedCalendar(InMemoryCalendarStore(), service)
    sunday = datetime(2026, 10, 18, 4, 0, tzinfo=UTC)  # the night before the leave starts
    following = run(calendar.next_event(sunday))
    assert following.title == "Incident review" and not following.all_day  # not "Annual leave" at midnight
