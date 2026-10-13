"""ADR 0035: parsing the ICS feed and classifying events. The syntax, recurrence and time zones are the libraries' work; these tests pin what this code makes of them: DATE versus
DATE-TIME, the exclusive end of an all-day event, leave, meeting signals, hidden details, recurrence exceptions, identity and the reminder decision. Fixtures are synthetic."""

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from companion_core.calendar.classify import (
    Basis,
    ClassificationRules,
    EventClass,
    apply_override,
    classify,
    reminder_decision,
)
from companion_core.calendar.ics import FeedError, parse_feed

FIXTURES = Path(__file__).parent / "fixtures" / "calendar"
SGT = ZoneInfo("Asia/Singapore")
OWNER = "owner@example.com"
WINDOW = (datetime(2026, 10, 10, tzinfo=UTC), datetime(2026, 11, 15, tzinfo=UTC))
RULES = ClassificationRules(owner_emails=[OWNER])


def parse(name_or_bytes, **kw):
    data = name_or_bytes if isinstance(name_or_bytes, bytes) else (FIXTURES / f"{name_or_bytes}.ics").read_bytes()
    return parse_feed(data, window_start=WINDOW[0], window_end=WINDOW[1], tz=SGT, owner_emails={OWNER}, **kw)


def by_title(parsed, title):
    return [f for f in parsed.facts if f.title == title]


def one(parsed, title):
    found = by_title(parsed, title)
    assert len(found) == 1, (title, len(found))
    return found[0]


def ics(*events: str) -> bytes:
    return ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\n" + "\n".join(events) + "\nEND:VCALENDAR\n").encode()


def event(uid: str, *lines: str) -> str:
    return "BEGIN:VEVENT\nUID:" + uid + "\nDTSTAMP:20261001T000000Z\n" + "\n".join(lines) + "\nEND:VEVENT"


@pytest.fixture(scope="module")
def work():
    return parse("work-calendar")


# --- all-day versus timed: the DTSTART value type, not the length ----------------------------------------------------------------------------------------------

def test_value_type_decides_all_day_not_duration():
    parsed = parse(ics(
        event("timed24", "DTSTART;TZID=Asia/Singapore:20261013T000000", "DTEND;TZID=Asia/Singapore:20261014T000000", "SUMMARY:Round the clock support"),
        event("dated", "DTSTART;VALUE=DATE:20261013", "DTEND;VALUE=DATE:20261014", "SUMMARY:Company day"),
    ))
    assert not one(parsed, "Round the clock support").all_day  # twenty-four hours but DATE-TIME: timed
    assert one(parsed, "Company day").all_day
    assert classify(one(parsed, "Company day"), RULES).event_class is EventClass.ALL_DAY
    assert classify(one(parsed, "Round the clock support"), RULES).event_class is EventClass.UNKNOWN_TIMED


def test_multi_day_all_day_respects_the_exclusive_end(work):
    leave = one(work, "Annual leave")
    assert leave.all_day
    assert leave.start == datetime(2026, 10, 19, tzinfo=SGT) and leave.end == datetime(2026, 10, 22, tzinfo=SGT)  # 19th, 20th, 21st; not the 22nd
    ends_on_the_22nd = parse(ics(event("m", "DTSTART;VALUE=DATE:20261019", "DTEND;VALUE=DATE:20261022", "SUMMARY:Retreat")))
    assert one(ends_on_the_22nd, "Retreat").end == datetime(2026, 10, 22, tzinfo=SGT)


def test_an_all_day_event_without_an_end_is_one_day():
    fact = one(parse(ics(event("a", "DTSTART;VALUE=DATE:20261013", "SUMMARY:Open day"))), "Open day")
    assert fact.all_day and fact.end - fact.start == (datetime(2026, 10, 14, tzinfo=SGT) - datetime(2026, 10, 13, tzinfo=SGT))


def test_all_day_event_by_duration_property():
    fact = one(parse(ics(event("d", "DTSTART;VALUE=DATE:20261013", "DURATION:P3D", "SUMMARY:Three days"))), "Three days")
    assert fact.all_day and fact.end == datetime(2026, 10, 16, tzinfo=SGT)


# --- leave -----------------------------------------------------------------------------------------------------------------------------------------------------

def test_multi_day_and_single_day_leave(work):
    multi, single = one(work, "Annual leave"), one(work, "Day off")
    assert classify(multi, RULES).event_class is EventClass.LEAVE_OR_OOO and classify(single, RULES).event_class is EventClass.LEAVE_OR_OOO
    assert single.end - single.start == datetime(2026, 10, 31, tzinfo=SGT) - datetime(2026, 10, 30, tzinfo=SGT)


def test_out_of_office_status_is_explicit_and_beats_a_neutral_title(work):
    away = one(work, "Away")
    result = classify(away, RULES)
    assert result.event_class is EventClass.LEAVE_OR_OOO and result.basis is Basis.EXPLICIT and not away.all_day


def test_a_non_leave_all_day_event_stays_all_day(work):
    assert classify(one(work, "Team offsite"), RULES).event_class is EventClass.ALL_DAY


def test_a_leave_word_does_not_make_a_real_meeting_leave():
    parsed = parse(ics(event(
        "h", "DTSTART;TZID=Asia/Singapore:20261013T100000", "DTEND;TZID=Asia/Singapore:20261013T110000", "SUMMARY:Holiday planning",
        "ATTENDEE:mailto:a@example.com", "ATTENDEE:mailto:b@example.com", "LOCATION:https://meet.google.com/abc-defg-hij",
    )))
    assert classify(one(parsed, "Holiday planning"), RULES).event_class is EventClass.MEETING


def test_leave_words_match_whole_words_only():
    parsed = parse(ics(event("l", "DTSTART;TZID=Asia/Singapore:20261013T100000", "DTEND;TZID=Asia/Singapore:20261013T110000", "SUMMARY:Leaving drinks")))
    assert classify(one(parsed, "Leaving drinks"), RULES).event_class is EventClass.UNKNOWN_TIMED


# --- timed events -----------------------------------------------------------------------------------------------------------------------------------------------

def test_attendees_make_an_explicit_meeting(work):
    result = classify(one(work, "Design review"), RULES)
    assert (result.event_class, result.basis) == (EventClass.MEETING, Basis.EXPLICIT) and "attendees" in result.reasons


def test_conferencing_metadata_makes_an_explicit_meeting_without_attendees(work):
    result = classify(one(work, "Vendor call"), RULES)
    assert (result.event_class, result.basis, result.reasons) == (EventClass.MEETING, Basis.EXPLICIT, ["conference"])


def test_structured_conference_property_counts():
    parsed = parse(ics(event(
        "c", "DTSTART;TZID=Asia/Singapore:20261013T100000", "DTEND;TZID=Asia/Singapore:20261013T110000", "SUMMARY:Quiet",
        "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
    )))
    assert classify(one(parsed, "Quiet"), RULES).reasons == ["conference"]


def test_a_title_word_alone_is_a_rule_based_meeting(work):
    result = classify(one(work, "Floating sync"), RULES)
    assert (result.event_class, result.basis) == (EventClass.MEETING, Basis.RULE)


def test_personal_appointment_is_separate_from_meeting(work):
    assert classify(one(work, "Dentist appointment"), RULES).event_class is EventClass.PERSONAL_APPOINTMENT


def test_unidentifiable_timed_event_is_unknown_not_a_guessed_meeting(work):
    result = classify(one(work, "Quiet time"), RULES)
    assert result.event_class is EventClass.UNKNOWN_TIMED and result.reasons == ["no_signal"]


def test_the_owner_alone_as_attendee_is_not_evidence_of_a_meeting():
    parsed = parse(ics(event("o", "DTSTART;TZID=Asia/Singapore:20261013T100000", "DTEND;TZID=Asia/Singapore:20261013T110000", "SUMMARY:Solo", f"ATTENDEE:mailto:{OWNER}")))
    assert classify(one(parsed, "Solo"), RULES).event_class is EventClass.UNKNOWN_TIMED
    assert classify(one(parsed, "Solo"), ClassificationRules()).event_class is EventClass.UNKNOWN_TIMED  # owner address unknown: one attendee proves nothing


def test_rules_are_configurable():
    parsed = parse(ics(event("k", "DTSTART;TZID=Asia/Singapore:20261013T100000", "DTEND;TZID=Asia/Singapore:20261013T110000", "SUMMARY:Pottery class")))
    fact = one(parsed, "Pottery class")
    assert classify(fact, RULES).event_class is EventClass.UNKNOWN_TIMED
    assert classify(fact, ClassificationRules(personal_keywords=["pottery"])).event_class is EventClass.PERSONAL_APPOINTMENT


# --- hidden details ---------------------------------------------------------------------------------------------------------------------------------------------

def test_private_events_keep_only_their_time(work):
    hidden = [f for f in work.facts if f.redacted and f.source_uid == "private@fixture"]
    assert len(hidden) == 1
    blob = hidden[0].model_dump_json()
    for secret in ("Secret hospital", "Ward 7", "doctor@example.com", "nurse@example.com"):
        assert secret not in blob
    assert classify(hidden[0], RULES).event_class is EventClass.BUSY_PRIVATE


def test_a_free_busy_publishers_busy_title_is_treated_as_hidden(work):
    busy = next(f for f in work.facts if f.source_uid == "busy-title@fixture")
    assert busy.redacted and busy.title is None


def test_no_description_is_ever_stored(work):
    assert "Agenda is private" not in json.dumps([f.model_dump(mode="json") for f in work.facts])


def test_free_busy_blocks_become_redacted_entries_and_free_time_is_not_busy():
    parsed = parse("freebusy-only")
    assert len(parsed.facts) == 4  # two busy, one tentative, the "Private appointment" event; the FBTYPE=FREE block is ignored
    assert all(f.redacted and f.title is None and f.location is None for f in parsed.facts)
    assert {classify(f, RULES).event_class for f in parsed.facts} == {EventClass.BUSY_PRIVATE}
    durations = sorted((f.end - f.start).total_seconds() for f in parsed.facts)
    assert 1800 in durations  # PT30M


# --- the reminder decision --------------------------------------------------------------------------------------------------------------------------------------

def decision(fact, rules=RULES, override=None, leave=()):
    return reminder_decision(fact, apply_override(classify(fact, rules), override), rules, list(leave))


def test_only_confirmed_or_identifiable_meetings_get_a_reminder(work):
    expected = {
        "Design review": None, "Vendor call": None, "Floating sync": None, "Roadmap discussion": None, "NY standup": None,
        "Cancelled planning meeting": "cancelled", "Budget review": "declined", "Annual leave": "all_day", "Day off": "all_day", "Team offsite": "all_day",
        "Away": "not_a_meeting:leave_or_ooo", "Dentist appointment": "not_a_meeting:personal_appointment", "Quiet time": "not_a_meeting:unknown_timed",
    }
    for title, why in expected.items():
        for fact in by_title(work, title):
            assert decision(fact) == why, title
    assert all(decision(f) == "not_a_meeting:busy_private" for f in work.facts if f.redacted)


def test_cancelled_occurrence_of_a_recurring_meeting_is_blocked_but_its_siblings_are_not(work):
    sync = [f for f in work.facts if f.series_key == one(work, "Weekly sync (moved)").series_key]
    states = {f.start.strftime("%d %b"): decision(f) for f in sync}
    assert states["02 Nov"] == "cancelled" and states["12 Oct"] is None and states["09 Nov"] is None


def test_keyword_meetings_can_be_excluded_by_rule(work):
    strict = ClassificationRules(owner_emails=[OWNER], remind_keyword_meetings=False)
    assert decision(one(work, "Floating sync"), strict) == "unconfirmed_meeting"
    assert decision(one(work, "Design review"), strict) is None  # explicit evidence still counts


def test_owner_override_wins_and_is_recorded(work):
    dentist = one(work, "Dentist appointment")
    result = apply_override(classify(dentist, RULES), "meeting")
    assert (result.event_class, result.basis, result.reasons) == (EventClass.MEETING, Basis.OWNER, ["owner_override"])
    assert decision(dentist, override="meeting") is None
    assert decision(one(work, "Design review"), override="unknown_timed") == "not_a_meeting:unknown_timed"
    assert apply_override(classify(dentist, RULES), "nonsense").event_class is EventClass.PERSONAL_APPOINTMENT  # an unknown class is ignored


def test_a_leave_day_does_not_suppress_a_meeting_unless_the_owner_turns_that_on(work):
    leave = one(work, "Annual leave")
    review = one(work, "Incident review")  # 20 Oct 15:00, inside the leave
    assert decision(review, leave=[(leave.start, leave.end)]) is None
    on = ClassificationRules(owner_emails=[OWNER], leave_suppresses_meetings=True)
    assert decision(review, on, leave=[(leave.start, leave.end)]) == "on_leave"
    assert decision(one(work, "Design review"), on, leave=[(leave.start, leave.end)]) is None  # a meeting on another day is untouched


# --- recurrence, identity, time zones ---------------------------------------------------------------------------------------------------------------------------

def test_recurrence_exceptions_are_applied(work):
    titles = {f.start.strftime("%d %b %H:%M"): f.title for f in work.facts if f.series_key == one(work, "Weekly sync (moved)").series_key}
    assert "19 Oct 09:30" not in titles  # EXDATE
    assert titles["26 Oct 11:00"] == "Weekly sync (moved)" and "26 Oct 09:30" not in titles  # moved instance replaces the original
    assert titles["02 Nov 09:30"] == "Weekly sync"  # present, marked cancelled
    assert [f.status for f in work.facts if f.start == datetime(2026, 11, 2, 9, 30, tzinfo=SGT)] == ["cancelled"]


def test_identity_is_stable_across_parses_and_across_a_reschedule(work):
    again = parse("work-calendar")
    assert [f.key for f in work.facts] == [f.key for f in again.facts]
    moved = one(work, "Weekly sync (moved)")
    assert moved.key.endswith(":20261026T013000Z")  # the ORIGINAL start, so moving the instance keeps its identity
    assert moved.series_key == by_title(work, "Weekly sync")[0].series_key
    assert len({f.key for f in work.facts}) == len(work.facts)


def test_a_rescheduled_single_event_keeps_its_key_and_changes_its_revision():
    first = parse(ics(event("r", "DTSTART;TZID=Asia/Singapore:20261013T100000", "DTEND;TZID=Asia/Singapore:20261013T110000", "SUMMARY:Review", "ATTENDEE:mailto:a@example.com", "ATTENDEE:mailto:b@example.com")))
    later = parse(ics(event("r", "DTSTART;TZID=Asia/Singapore:20261013T140000", "DTEND;TZID=Asia/Singapore:20261013T150000", "SUMMARY:Review", "ATTENDEE:mailto:a@example.com", "ATTENDEE:mailto:b@example.com", "SEQUENCE:1")))
    a, b = one(first, "Review"), one(later, "Review")
    assert a.key == b.key and a.revision != b.revision and b.start.hour == 14


def test_dst_transition_keeps_the_wall_clock_time(work):
    standups = sorted((f for f in work.facts if f.title == "NY standup"), key=lambda f: f.start)
    utc_hours = [f.start.astimezone(UTC).hour for f in standups]
    assert utc_hours == [13, 13, 14]  # 09:00 in New York is 13:00Z until 1 Nov and 14:00Z after
    assert all(f.start.astimezone(ZoneInfo("America/New_York")).hour == 9 for f in standups)


def test_floating_times_are_read_in_the_owners_zone(work):
    assert one(work, "Floating sync").start == datetime(2026, 10, 21, 9, 0, tzinfo=SGT)


def test_missing_title_is_not_invented(work):
    untitled = next(f for f in work.facts if f.source_uid == "untitled@fixture")
    assert untitled.title is None and not untitled.redacted
    assert classify(untitled, RULES).event_class is EventClass.MEETING


def test_cancelled_and_tentative_status_are_kept(work):
    assert one(work, "Cancelled planning meeting").status == "cancelled"
    assert one(work, "Roadmap discussion").status == "tentative"
    assert one(work, "Budget review").owner_response == "declined"


def test_a_cancel_method_feed_marks_everything_cancelled():
    body = ics(event("x", "DTSTART;TZID=Asia/Singapore:20261013T100000", "DTEND;TZID=Asia/Singapore:20261013T110000", "SUMMARY:Gone")).replace(b"VERSION:2.0", b"VERSION:2.0\nMETHOD:CANCEL")
    assert one(parse(body), "Gone").status == "cancelled"


def test_garbage_is_rejected_with_a_fixed_code_that_quotes_nothing():
    with pytest.raises(FeedError) as caught:
        parse(b"BEGIN:VCALENDAR\nthis is not a calendar secret-token-123")
    assert caught.value.code == "not_calendar" and "secret-token" not in str(caught.value)


def test_one_broken_event_does_not_lose_the_rest():
    parsed = parse(ics(
        event("bad", "SUMMARY:No start at all"),
        event("good", "DTSTART;TZID=Asia/Singapore:20261013T100000", "DTEND;TZID=Asia/Singapore:20261013T110000", "SUMMARY:Fine"),
    ))
    assert [f.title for f in parsed.facts] == ["Fine"]


def test_the_cap_truncates_and_says_so():
    many = ics(*[event(f"e{i}", f"DTSTART;TZID=Asia/Singapore:202610{13 + i // 20:02d}T{9 + i % 10:02d}0000", f"DTEND;TZID=Asia/Singapore:202610{13 + i // 20:02d}T{9 + i % 10:02d}3000", f"SUMMARY:E{i}") for i in range(40)])
    parsed = parse(many, max_events=10)
    assert len(parsed.facts) == 10 and parsed.truncated
