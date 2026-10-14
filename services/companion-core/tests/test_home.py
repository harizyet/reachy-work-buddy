"""Home dashboard (docs/phase-51.md): the snapshot, its privacy filtering, the weather adapter, the deterministic briefing and the optional wording of it. In-process evidence (in-memory
stores, a scripted weather provider and model, a fixed clock) plus the real FastAPI app for the routes and the calendar revision; no network, no real model."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from companion_core.app import create_app
from companion_core.briefing import BriefingCategory, build_briefing, home_items
from companion_core.calendar.feed import (
    CalendarFeedService,
    InMemoryFeedStore,
)
from companion_core.calendar.models import CalendarEvent
from companion_core.calendar.safe_fetch import FeedFetcher
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.home import build_home
from companion_core.home_brief import build_brief, grounded
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meeting_analysis.models import Evidence, Item, ItemKind, ItemStatus
from companion_core.meeting_analysis.store import InMemoryMeetingAnalysisStore
from companion_core.meetings.models import Meeting, MeetingJobStatus
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.notepad_processing.models import (
    Kind,
    Proposal,
    ProposalStatus,
    Provenance,
)
from companion_core.notepad_processing.store import InMemoryNotepadStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.semantic.access import access_for_owner
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.weather import WeatherService
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.persona import PersonaConfig
from shared.models.response import Privacy
from shared.protocols.document_library_api import ACCESS_CEILING_HEADER

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)  # 14:00 in Singapore
PERSONA = PersonaConfig(location="Singapore", timezone="Asia/Singapore")
OWNER = access_for_owner("owner", channel_private=True)
SENSITIVE_OWNER = access_for_owner("owner", channel_private=True, allow_sensitive=True)
PUBLIC = access_for_owner("owner", channel_private=False)


def run(coro):
    return asyncio.run(coro)


def at(hour, minute=0, day=0):
    """A Singapore wall-clock time on the test day, as an instant."""
    return datetime(2026, 10, 14, hour, minute, tzinfo=UTC) + timedelta(days=day) - timedelta(hours=8)


class Calendar:
    """The slice of CalendarStore Home uses, over events whose classification is already set (as FeedCalendar sets it)."""

    def __init__(self, *events):
        self.events = list(events)

    async def list_events(self, start, end):
        return [e for e in self.events if e.start < end and e.end > start]

    async def next_event(self, after):
        later = [e for e in self.events if e.start >= after and not e.all_day and e.classification != "leave_or_ooo" and e.status != "cancelled"]
        return min(later, key=lambda e: e.start, default=None)


def event(title, start, end, **over):
    return CalendarEvent(title=title, start=start, end=end, classification=over.pop("classification", "meeting"), event_key=over.pop("event_key", f"key-{title}"), **over)


class Env:
    def __init__(self, calendar=None, weather=None):
        self.calendar = calendar or Calendar()
        self.tasks, self.planner, self.meetings = InMemoryTaskStore(), InMemoryPlannerStore(), InMemoryMeetingStore()
        self.notepad_store, self.analysis_store = InMemoryNotepadStore(), InMemoryMeetingAnalysisStore()

        class Notepad:  # the slice of NotepadService Home reads
            store, planner = self.notepad_store, self.planner

        class Analysis:
            store, meetings = self.analysis_store, self.meetings

        self.notepad, self.analysis, self.weather = Notepad(), Analysis(), weather
        self.notepad_on = self.analysis_on = True

    def home(self, access=OWNER, sections=("schedule", "tasks", "reminders", "reviews", "weather"), now=NOW):
        return run(build_home(access=access, now=now, persona=PERSONA, calendar_store=self.calendar, task_store=self.tasks, planner_store=self.planner,
                              notepad_service=self.notepad if self.notepad_on else None, analysis_service=self.analysis if self.analysis_on else None, weather=self.weather, sections=sections))

    def proposal(self, text, *, sensitivity=Privacy.WORK_PRIVATE, scope=None, status=ProposalStatus.PENDING, note_id="n1"):
        p = Proposal(job_id="j", note_id=note_id, snapshot_hash="h", kind=Kind.TASK, text=text, evidence=text, span_start=0, span_end=1, status=status, fingerprint=f"f-{text}",
                     sensitivity=sensitivity, project_scope=scope)
        self.notepad_store._proposals[p.id] = p
        return p

    def candidate(self, text, *, sensitivity=Privacy.WORK_PRIVATE, scope=None, status=ItemStatus.PENDING, kind=ItemKind.ACTION, record_id=None, meeting_id="m1"):
        i = Item(run_id="r", meeting_id=meeting_id, transcript_hash="t", kind=kind, text=text, evidence=[Evidence(segment=0, start=0, end=1, quote=text)], status=status, fingerprint=f"f-{text}",
                 sensitivity=sensitivity, project_scope=scope, record_id=record_id, record_kind="task" if record_id else None)
        self.analysis_store._items[i.id] = i
        return i


# -- schedule ---------------------------------------------------------------------------------------------------------------------------------

def test_today_is_the_owners_local_day_and_the_next_event_is_reported():
    env = Env(Calendar(
        event("Standup", at(9), at(9, 30)), event("Review", at(15), at(16)), event("Yesterday", at(9, day=-1), at(10, day=-1)),
        event("Tomorrow", at(9, day=1), at(10, day=1)), event("Late", at(23, 30), at(23, 59)),
    ))
    schedule = env.home()["schedule"]
    assert schedule["date"] == "2026-10-14" and schedule["timezone"] == "Asia/Singapore"
    assert [e["title"] for e in schedule["events"]] == ["Standup", "Review", "Late"]  # the local day, not the UTC day, and chronological
    assert schedule["next_event"]["title"] == "Review" and schedule["next_event"]["ref"] == {"screen": "calendar", "id": "key-Review"}
    assert schedule["status"] == "ok" and schedule["counts"] == {"timed": 3, "all_day": 0}


def test_an_empty_day_is_empty_not_unavailable_and_the_next_event_may_be_tomorrow():
    env = Env(Calendar(event("Tomorrow", at(9, day=1), at(10, day=1))))
    schedule = env.home()["schedule"]
    assert schedule["status"] == "empty" and schedule["events"] == [] and schedule["next_event"]["title"] == "Tomorrow"


def test_leave_and_busy_only_events_are_classified_and_never_get_invented_text():
    env = Env(Calendar(
        event("Annual leave", at(0), at(0, day=1), all_day=True, classification="leave_or_ooo"),
        event("Dentist at Raffles Clinic", at(11), at(12), classification="busy_private", location="Raffles Clinic", event_key="opaque-1"),
        event("Busy", at(16), at(17), classification="unknown_timed", redacted=True, location="Secret room", event_key="opaque-2"),
        event("Visible", at(17), at(18)),
    ))
    schedule = env.home()["schedule"]
    assert schedule["on_leave"] is True and [e["title"] for e in schedule["all_day"]] == ["Annual leave"] and schedule["all_day"][0]["classification"] == "leave_or_ooo"
    hidden = [e for e in schedule["events"] if e["title"] == "Busy"]
    assert len(hidden) == 2 and all(e["location"] is None for e in hidden)  # a busy-only or redacted event carries its placeholder and nothing else
    everything = json.dumps(schedule)
    assert "Raffles" not in everything and "Secret room" not in everything
    assert all(set(e) == {"id", "event_key", "title", "start", "end", "all_day", "classification", "location", "status", "response", "redacted", "recurring", "remind", "ref"} for e in schedule["events"])
    assert schedule["next_event"]["title"] != "Annual leave"  # a leave day is not "what's next"


def test_cancelled_and_declined_events_are_not_on_the_schedule():
    env = Env(Calendar(event("Cancelled", at(9), at(10), status="cancelled"), event("Declined", at(10), at(11), response="declined"), event("Kept", at(11), at(12), response="accepted")))
    assert [e["title"] for e in env.home()["schedule"]["events"]] == ["Kept"]


# -- tasks and reminders --------------------------------------------------------------------------------------------------------------------

def test_open_tasks_are_listed_without_due_dates_and_done_tasks_are_not():
    env = Env()
    run(env.tasks.add_task("Write report"))
    done = run(env.tasks.add_task("Old thing"))
    run(env.tasks.complete_task(done.id))
    tasks = env.home()["tasks"]
    assert tasks["total"] == 1 and tasks["has_due_dates"] is False and [t["text"] for t in tasks["items"]] == ["Write report"]
    assert "due" not in json.dumps(tasks["items"][0]) and tasks["items"][0]["ref"]["screen"] == "tasks"


def test_reminders_split_into_overdue_today_and_upcoming_in_the_owners_timezone():
    env = Env()
    for text, due in (("Overdue", at(9)), ("Tonight", at(21)), ("Next week", at(10, day=5)), ("Far away", at(10, day=30))):
        run(env.planner.add_reminder(text, due))
    done = run(env.planner.add_reminder("Finished", at(20)))
    run(env.planner.complete_reminder(done.id))
    reminders = env.home()["reminders"]
    assert reminders["counts"] == {"overdue": 1, "today": 1, "upcoming": 1}
    assert [r["text"] for r in reminders["overdue"]] == ["Overdue"] and [r["text"] for r in reminders["today"]] == ["Tonight"] and [r["text"] for r in reminders["upcoming"]] == ["Next week"]


def test_a_reminder_after_local_midnight_but_before_utc_midnight_belongs_to_the_owners_tomorrow():
    env = Env()
    run(env.planner.add_reminder("After midnight there", datetime(2026, 10, 14, 16, 30, tzinfo=UTC)))  # 00:30 on the 15th in Singapore
    assert env.home()["reminders"]["counts"] == {"overdue": 0, "today": 0, "upcoming": 1}


# -- pending suggestions and confirmed actions ----------------------------------------------------------------------------------------------------

def test_pending_proposals_are_counted_as_suggestions_never_as_tasks():
    env = Env()
    run(env.planner.add_note("Weekly", "body"))
    env.proposal("Renew the certificate")
    env.proposal("Already decided", status=ProposalStatus.DISMISSED)
    env.candidate("Contact the vendor")
    env.candidate("A decision", kind=ItemKind.DECISION, status=ItemStatus.NOTED)
    home = env.home()
    assert home["tasks"]["status"] == "empty" and home["tasks"]["total"] == 0
    reviews = home["reviews"]
    assert reviews["note_proposals"]["count"] == 1 and reviews["meeting_actions"]["count"] == 1 and reviews["total"] == 2
    assert all(i["pending_review"] is True for i in reviews["note_proposals"]["items"] + reviews["meeting_actions"]["items"])
    assert run(env.tasks.list_tasks()) == []  # building the snapshot promoted nothing


def test_a_confirmed_meeting_action_is_one_task_with_its_origin_and_not_also_a_suggestion():
    env = Env()
    env.meetings._meetings["m1"] = Meeting(id="m1", title="Cluster migration", source_filename="a", content_type="audio/wav", audio_path="/x", status=MeetingJobStatus.COMPLETE)
    task = run(env.tasks.add_task("Alice: Contact the vendor"))
    env.candidate("Contact the vendor", status=ItemStatus.ACCEPTED, record_id=task.id)
    env.candidate("Update the schedule")
    home = env.home()
    assert home["tasks"]["total"] == 1 and home["tasks"]["from_meetings"] == 1
    assert home["tasks"]["items"][0]["origin"] == {"kind": "meeting", "meeting_id": "m1", "meeting_title": "Cluster migration"}
    assert home["reviews"]["meeting_actions"]["count"] == 1 and home["reviews"]["meeting_actions"]["items"][0]["text"] == "Update the schedule"  # only the undecided one
    brief = [line for line in home_items(home) if line["category"] == "task"]
    assert "1 open task, 1 from meetings" in brief[0]["text"]


def test_a_task_from_an_accepted_note_proposal_shows_its_note():
    env = Env()
    note = run(env.planner.add_note("Weekly", "body"))
    task = run(env.tasks.add_task("Renew the certificate"))
    env.notepad_store._provenance[("task", task.id)] = Provenance(record_kind="task", record_id=task.id, note_id=note.id, proposal_id="p", snapshot_hash="h")
    assert env.home()["tasks"]["items"][0]["origin"] == {"kind": "note", "note_id": note.id, "note_title": "Weekly"}


def test_features_that_are_off_say_off_and_do_not_count():
    env = Env()
    env.notepad_on = env.analysis_on = False
    assert env.home()["reviews"] == {"status": "off", "total": 0, "note_proposals": {"status": "off", "count": 0, "items": []}, "meeting_actions": {"status": "off", "count": 0, "items": []}}


# -- privacy ------------------------------------------------------------------------------------------------------------------------------------

def seeded_with_sensitive():
    env = Env(Calendar(event("Standup", at(9), at(10))))
    run(env.tasks.add_task("Plain task"))
    run(env.tasks.add_task("Salary negotiation notes", sensitivity=Privacy.SENSITIVE))
    run(env.tasks.add_task("Scoped task", project_scope="apollo"))
    run(env.planner.add_reminder("Plain reminder", at(20)))
    run(env.planner.add_reminder("Call the clinic about results", at(21), sensitivity=Privacy.SENSITIVE))
    env.proposal("Plain proposal")
    env.proposal("Sensitive proposal about medication", sensitivity=Privacy.SENSITIVE)
    env.candidate("Plain action")
    env.candidate("Sensitive action about layoffs", sensitivity=Privacy.SENSITIVE)
    return env


def test_records_above_the_ceiling_change_neither_lists_nor_counts():
    home = seeded_with_sensitive().home()  # the owner's trusted dashboard ceiling is work-private
    assert home["tasks"]["total"] == 2 and "Salary" not in json.dumps(home)
    assert home["reminders"]["counts"]["today"] == 1 and "clinic" not in json.dumps(home)
    assert home["reviews"]["note_proposals"]["count"] == 1 and home["reviews"]["meeting_actions"]["count"] == 1
    assert all(w not in json.dumps(home) for w in ("medication", "layoffs"))
    assert any("Plain proposal" in i["text"] for i in home["reviews"]["note_proposals"]["items"])


def test_a_higher_ceiling_sees_the_sensitive_records_and_a_project_scope_limits_what_is_seen():
    env = seeded_with_sensitive()
    assert env.home(SENSITIVE_OWNER)["tasks"]["total"] == 3
    scoped = access_for_owner("owner", channel_private=True, project_scopes=frozenset({"other"}))
    assert env.home(scoped)["tasks"]["total"] == 1  # the "apollo" task is outside the scope; the unscoped one stays


def test_a_public_context_gets_no_content_and_no_counts_not_even_that_records_exist():
    home = seeded_with_sensitive().home(PUBLIC)
    for name in ("schedule", "tasks", "reminders", "reviews", "weather"):
        assert home[name] == {"status": "restricted"}
    assert home["restricted"] is True and home["quick_actions"] == [] and home["partial"] is False
    text = json.dumps(home)
    for leaked in ("Standup", "Plain", "total", "count", "counts", "Salary"):
        assert leaked not in text
    assert home_items(home) == []


# -- partial failure and sections ----------------------------------------------------------------------------------------------------------------

def test_one_failing_source_marks_only_its_own_section():
    env = Env(Calendar(event("Standup", at(9), at(10))))
    run(env.tasks.add_task("Still here"))

    async def broken(*a, **k):
        raise RuntimeError("secret record text must not be echoed")

    env.planner.list_reminders = broken
    home = env.home()
    assert home["reminders"] == {"status": "unavailable", "error": "section_failed"} and home["tasks"]["total"] == 1 and home["schedule"]["status"] == "ok"
    assert home["partial"] is True and home["sources"]["reminders"] == "unavailable" and "secret record text" not in json.dumps(home)
    assert "The calendar could not be read" not in json.dumps(home_items(home))  # the calendar is fine; only the reminders section is unavailable


def test_one_review_queue_failing_is_partial_not_a_zero():
    env = Env()
    env.candidate("Contact the vendor")

    async def broken(*a, **k):
        raise RuntimeError("x")

    env.notepad_store.list_proposals = broken
    reviews = env.home()["reviews"]
    assert reviews["status"] == "partial" and reviews["note_proposals"]["status"] == "unavailable" and reviews["meeting_actions"]["count"] == 1


def test_named_sections_refresh_on_their_own():
    env = Env()
    run(env.tasks.add_task("T"))
    home = env.home(sections=("tasks",))
    assert set(home["sources"]) == {"tasks"} and "schedule" not in home and home["tasks"]["total"] == 1


def test_quick_actions_come_from_the_snapshot():
    env = Env(Calendar(event("Standup", at(15), at(16))))
    env.proposal("A proposal")
    ids = [q["id"] for q in env.home()["quick_actions"]]
    assert ids[:2] == ["record_meeting", "review_notes"] and ids[-3:] == ["add_task", "new_note", "ask"]


# -- weather ------------------------------------------------------------------------------------------------------------------------------------

FORECAST = {
    "current": {"time": "2026-10-14T14:00", "temperature_2m": 30.4, "apparent_temperature": 36.0, "relative_humidity_2m": 78, "precipitation": 0.4, "weather_code": 61, "wind_speed_10m": 9.3, "is_day": 1},
    "daily": {"time": ["2026-10-14"], "weather_code": [80], "temperature_2m_max": [32.1], "temperature_2m_min": [26.0], "precipitation_sum": [7.5], "precipitation_probability_max": [85],
              "sunrise": ["2026-10-14T06:58"], "sunset": ["2026-10-14T18:55"]},
}
GEOCODE = {"results": [{"name": "Singapore", "latitude": 1.29, "longitude": 103.85, "country": "Singapore", "admin1": "Central"}, {"name": "Singapore", "latitude": 5.0, "longitude": 5.0, "country": "Elsewhere"}]}


class Provider:
    def __init__(self):
        self.calls, self.fail, self.forecast, self.geocode = [], None, FORECAST, GEOCODE
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        self.calls.append(request)
        if self.fail == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if self.fail:
            return httpx.Response(self.fail)
        return httpx.Response(200, json=self.geocode if "geocoding" in request.url.host else self.forecast)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def weather_service(provider, clock=None, **over):
    return WeatherService(transport=provider.transport, clock=clock or Clock(), cache_seconds=over.pop("cache_seconds", 1800), timeout=2, stale_seconds=over.pop("stale_seconds", 6 * 3600), **over)


def test_weather_is_provider_data_with_attribution_timestamps_and_the_owners_timezone():
    provider = Provider()
    section = run(weather_service(provider).section("Singapore", "Asia/Singapore"))
    assert section["status"] == "ok" and section["location"] == "Singapore"
    assert section["current"]["temperature"] == 30.4 and section["current"]["summary"] == "Light rain" and section["current"]["raining"] is True
    assert section["today"]["high"] == 32.1 and section["today"]["precipitation_total"] == 7.5 and section["today"]["precipitation_probability"] == 85 and section["today"]["summary"] == "Light rain showers"
    assert section["observed_at"] == "2026-10-14T14:00:00+08:00" and section["today"]["sunset"] == "2026-10-14T18:55:00+08:00"
    assert section["attribution"]["name"] == "Open-Meteo.com" and section["fetched_at"] and section["units"]["temperature"] == "°C"
    forecast = next(r for r in provider.calls if r.url.host == "api.open-meteo.com")
    assert forecast.url.params["timezone"] == "Asia/Singapore" and forecast.url.params["latitude"] == "1.29"  # the geocoded point; the first result matched


def test_weather_is_cached_and_the_place_is_looked_up_once():
    provider, clock = Provider(), Clock()
    service = weather_service(provider, clock)
    run(service.section("Singapore", "Asia/Singapore"))
    clock.now += timedelta(minutes=10)
    assert run(service.section("Singapore", "Asia/Singapore"))["age_seconds"] == 600 and len(provider.calls) == 2  # geocode + forecast, nothing more
    clock.now += timedelta(minutes=30)
    run(service.section("Singapore", "Asia/Singapore"))
    assert len(provider.calls) == 3  # one more forecast; the place was remembered


def test_a_failed_refresh_shows_the_last_answer_as_stale_then_unavailable():
    provider, clock = Provider(), Clock()
    service = weather_service(provider, clock)
    run(service.section("Singapore", "Asia/Singapore"))
    provider.fail = 503
    clock.now += timedelta(hours=1)
    stale = run(service.section("Singapore", "Asia/Singapore"))
    assert stale["status"] == "stale" and stale["error"] == "provider_error" and stale["current"]["temperature"] == 30.4 and stale["age_seconds"] == 3600
    clock.now += timedelta(hours=7)
    gone = run(service.section("Singapore", "Asia/Singapore"))
    assert gone == {"status": "unavailable", "error": "provider_error", "attribution": gone["attribution"]} and "current" not in gone


def test_weather_failure_modes_are_fixed_codes():
    provider = Provider()
    provider.fail = "timeout"
    assert run(weather_service(provider).section("Singapore", "Asia/Singapore"))["error"] == "timeout"
    provider = Provider()
    provider.geocode = {"results": []}
    assert run(weather_service(provider).section("Nowhere", "Asia/Singapore"))["error"] == "location_not_found"
    provider = Provider()
    provider.forecast = {"current": {"time": "bad"}, "daily": {}}
    assert run(weather_service(provider).section("Singapore", "Asia/Singapore"))["error"] == "bad_response"
    assert run(weather_service(Provider()).section(None, "Asia/Singapore")) == {"status": "not_configured", "detail": "no_location"}
    assert run(weather_service(Provider(), is_enabled=False).section("Singapore", "Asia/Singapore")) == {"status": "off"}


def test_a_country_after_the_comma_picks_the_matching_place():
    provider = Provider()
    provider.geocode = {"results": [{"name": "Springfield", "latitude": 1.0, "longitude": 1.0, "country": "United States"}, {"name": "Springfield", "latitude": 2.0, "longitude": 2.0, "country": "Australia"}]}
    run(weather_service(provider).section("Springfield, Australia", "UTC"))
    assert next(r for r in provider.calls if r.url.host == "api.open-meteo.com").url.params["latitude"] == "2.0"


def test_weather_failing_does_not_touch_any_other_section():
    provider = Provider()
    provider.fail = 500
    env = Env(Calendar(event("Standup", at(9), at(10))), weather=weather_service(provider))
    run(env.tasks.add_task("T"))
    home = env.home()
    assert home["weather"]["status"] == "unavailable" and home["schedule"]["status"] == "ok" and home["tasks"]["total"] == 1
    assert home["partial"] is True


# -- the briefing ---------------------------------------------------------------------------------------------------------------------------------

def full_env():
    provider = Provider()
    env = Env(Calendar(event("Standup", at(9), at(9, 30)), event("Annual leave", at(0), at(0, day=1), all_day=True, classification="leave_or_ooo"), event("Review", at(15), at(16))),
              weather=weather_service(provider))
    run(env.tasks.add_task("Write report"))
    run(env.planner.add_reminder("Call the bank", at(17)))
    run(env.planner.add_reminder("Pay rent", at(8)))
    env.proposal("Renew the certificate")
    env.candidate("Contact the vendor")
    return env


def test_the_deterministic_briefing_separates_confirmed_records_from_suggestions():
    lines = home_items(full_env().home())
    by_status = {s: [x["text"] for x in lines if x["status"] == s] for s in ("confirmed", "pending_review", "info")}
    assert any("Standup" in t for t in by_status["confirmed"]) and any("All day: Annual leave" in t for t in by_status["confirmed"])
    assert any("Overdue reminder: Pay rent" in t for t in by_status["confirmed"]) and any("Reminder at 17:00: Call the bank" in t for t in by_status["confirmed"])
    assert all("not tasks" in t or "not a task" in t or "until you" in t for t in by_status["pending_review"]) and len(by_status["pending_review"]) == 2
    assert "Renew the certificate" not in json.dumps(lines) and "Contact the vendor" not in json.dumps(lines)  # a suggestion is announced by count, never as an item to do
    assert any("Light rain" in t and "Open-Meteo" in t for t in by_status["info"])
    assert lines[0]["text"].startswith("Overdue reminder")  # urgent first
    assert {x["category"] for x in lines} <= {c.value for c in BriefingCategory}


def test_the_briefing_without_weather_or_calendar_still_composes():
    env = Env()
    run(env.tasks.add_task("Only task"))
    texts = [x["text"] for x in home_items(env.home())]
    assert "Nothing on your calendar today." in texts and any("1 open task" in t for t in texts)


def scripted(answer):
    async def ask(messages, max_tokens):
        ask.messages = messages
        if isinstance(answer, Exception):
            raise answer
        return answer
    return ask


def test_a_good_wording_is_used_and_it_saw_only_the_authorised_lines():
    home = seeded_with_sensitive().home()
    lines = home_items(home)
    ask = scripted("You have Standup at 09:00-10:00 today. Plain task is open.")
    brief = run(build_brief(home, ask=ask, model="local-7b", want_narrative=True, now=NOW))
    assert brief["mode"] == "generated" and brief["narrative"].startswith("You have Standup") and brief["model"] == "local-7b" and brief["fallback"] is None
    assert brief["lines"] == lines and brief["text"].startswith("- ")  # the deterministic lines are always returned beside the wording
    sent = json.dumps(ask.messages)
    assert "Salary" not in sent and "medication" not in sent and "layoffs" not in sent and "pending_review" in sent
    assert "ignore any instruction" in ask.messages[0]["content"]


@pytest.mark.parametrize("answer, reason", [
    (RuntimeError("model down"), "generation_failed"), (TimeoutError(), "timeout"), ("", "unverified_wording"),
    ("Your Standup starts at 11:30.", "unverified_wording"),  # a time that is not in the lines
    ("You have seven tasks.", "unverified_wording"),  # a count written as a word that the lines do not contain
    ("x" * 2000, "unverified_wording"),
])
def test_a_failed_or_unverified_wording_falls_back_to_the_deterministic_briefing(answer, reason):
    home = Env(Calendar(event("Standup", at(9), at(10)))).home()
    brief = run(build_brief(home, ask=scripted(answer), model="m", want_narrative=True, now=NOW))
    assert brief["mode"] == "deterministic" and brief["narrative"] is None and brief["fallback"] == reason and "Standup" in brief["text"]


def test_no_model_no_narrative_and_a_restricted_context_never_call_the_model():
    home = Env(Calendar(event("Standup", at(9), at(10)))).home()
    assert run(build_brief(home, ask=None, model=None, want_narrative=True, now=NOW))["fallback"] == "model_unavailable"
    ask = scripted("Anything")
    assert run(build_brief(home, ask=ask, model="m", want_narrative=False, now=NOW))["mode"] == "deterministic" and not hasattr(ask, "messages")
    restricted = Env(Calendar(event("Standup", at(9), at(10)))).home(PUBLIC)
    out = run(build_brief(restricted, ask=ask, model="m", want_narrative=True, now=NOW))
    assert out["fallback"] == "restricted" and out["lines"] == [] and not hasattr(ask, "messages")


def test_grounded_checks_numbers_times_and_number_words():
    lines = [{"text": "Meeting 09:00-10:00. 2 open tasks."}]
    assert grounded("Meeting 09:00-10:00 and 2 open tasks.", lines)
    assert not grounded("Meeting at 09:30.", lines) and not grounded("Three open tasks.", lines) and not grounded("   ", lines)


def test_phase_18_briefing_is_unchanged_without_home():
    async def go():
        cal = InMemoryCalendarStore()
        await cal.add_event(CalendarEvent(title="Kickoff", start=NOW + timedelta(minutes=2), end=NOW + timedelta(minutes=30)))
        tasks = InMemoryTaskStore()
        await tasks.add_task("Follow up")
        return await build_briefing(calendar_store=cal, task_store=tasks, email_store=InMemoryEmailStore(), memory_store=InMemoryMemoryStore(), now=NOW)

    items = run(go())
    assert [i.category.value for i in items] == ["reminder", "calendar", "task"]


# -- the real app ---------------------------------------------------------------------------------------------------------------------------------

ICS = """BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\n{events}\nEND:VCALENDAR\n"""


def vevent(uid, start, end, summary, *extra):
    s = lambda d: d.strftime("%Y%m%dT%H%M%SZ")
    return "\n".join(["BEGIN:VEVENT", f"UID:{uid}", "DTSTAMP:20261001T000000Z", f"DTSTART:{s(start)}", f"DTEND:{s(end)}", f"SUMMARY:{summary}", *extra, "END:VEVENT"])


class World:
    def __init__(self, body):
        self.body = body

        async def resolve(host, port):
            return ["93.184.216.34"]

        self.service = CalendarFeedService(InMemoryFeedStore(), FeedFetcher(resolver=resolve, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=self.body, headers={"content-type": "text/calendar"}))))


def app_client(world, provider=None, model_answer="Standup at 09:00."):
    async def llm_provider():
        return scripted(model_answer), "scripted"

    app = create_app(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), calendar_store=InMemoryCalendarStore(), calendar_feed_service=world.service, run_calendar_feed_loop=False,
        task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        notepad_store=InMemoryNotepadStore(), notepad_provider=llm_provider, run_notepad_runner=False, weather_service=weather_service(provider or Provider()),
    )
    return TestClient(app)


def day_events():
    today = datetime.now(UTC).replace(hour=3, minute=0, second=0, microsecond=0)  # 03:00 UTC is inside the default persona's day whatever the date
    return today


def test_home_over_http_follows_the_calendar_revision_and_redacts_busy_events():
    today = day_events()
    first = ICS.format(events="\n".join([vevent("a", today, today + timedelta(minutes=30), "Standup"), vevent("p", today + timedelta(hours=1), today + timedelta(hours=2), "Secret errand", "CLASS:PRIVATE")]))
    world = World(first.encode())
    with app_client(world) as c:
        assert c.put("/calendar/feed", json={"url": "https://calendar.example.com/x.ics"}).status_code == 200
        before = c.get("/home", params={"sections": "schedule"}).json()
        titles = {e["title"] for e in before["schedule"]["events"]}
        assert "Standup" in titles and "Busy" in titles and "Secret errand" not in json.dumps(before)
        assert set(before) >= {"generated_at", "schedule", "sources", "partial", "quick_actions"} and "tasks" not in before
        generation = before["schedule"]["generation"]
        world.body = ICS.format(events=vevent("a", today, today + timedelta(minutes=30), "Standup moved") + "\n" + vevent("n", today + timedelta(hours=3), today + timedelta(hours=4), "Added")).encode()
        assert c.post("/calendar/feed/refresh").status_code == 200
        after = c.get("/home", params={"sections": "schedule"}).json()["schedule"]
        assert after["generation"] > generation and {e["title"] for e in after["events"]} == {"Standup moved", "Added"}


def test_home_routes_validate_sections_and_honour_the_ceiling_header():
    world = World(ICS.format(events="").encode())
    with app_client(world) as c:
        run_task = c.post("/tasks", json={"text": "Visible task"})
        assert run_task.status_code == 200
        c.post("/tasks", json={"text": "Hidden task", "sensitivity": "sensitive"})
        assert c.get("/home", params={"sections": "nope"}).status_code == 422
        assert c.get("/home", params={"sections": ""}).status_code in (200, 422)
        ok = c.get("/home", params={"sections": "tasks"}).json()
        assert ok["tasks"]["total"] == 1 and "Hidden task" not in json.dumps(ok)
        public = c.get("/home", headers={ACCESS_CEILING_HEADER: "public"}).json()
        assert public["tasks"] == {"status": "restricted"} and "Visible task" not in json.dumps(public)
        assert c.get("/home", headers={ACCESS_CEILING_HEADER: "bogus"}).status_code == 400
        assert c.get("/home", params={"sections": "reviews"}).json()["reviews"]["status"] == "off"  # Notepad processing off here: the feature flag is the owner's, not ours


def test_the_brief_route_returns_lines_and_a_verified_wording_or_the_lines_alone():
    today = day_events()
    world = World(ICS.format(events=vevent("a", today, today + timedelta(minutes=30), "Standup")).encode())
    with app_client(world, model_answer="You have Standup at 03:00-03:30.") as c:
        c.put("/calendar/feed", json={"url": "https://calendar.example.com/x.ics"})
        brief = c.post("/home/brief", json={}).json()
        assert brief["mode"] == "generated" and brief["narrative"] and brief["lines"] and brief["model"] == "scripted"
        plain = c.post("/home/brief", json={"narrative": False}).json()
        assert plain["mode"] == "deterministic" and plain["narrative"] is None and plain["lines"] == brief["lines"]
        assert c.post("/home/brief", json={"surprise": 1}).status_code == 422
        public = c.post("/home/brief", headers={ACCESS_CEILING_HEADER: "public"}, json={}).json()
        assert public["lines"] == [] and public["restricted"] is True and public["narrative"] is None
    with app_client(world, model_answer="Standup at 11:45.") as c:
        c.put("/calendar/feed", json={"url": "https://calendar.example.com/x.ics"})
        assert c.post("/home/brief", json={}).json()["fallback"] == "unverified_wording"


def test_the_existing_briefing_route_is_unchanged():
    with app_client(World(ICS.format(events="").encode())) as c:
        c.post("/tasks", json={"text": "Follow up"})
        assert [i["category"] for i in c.get("/briefing").json()] == ["task"]
