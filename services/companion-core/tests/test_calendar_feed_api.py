"""ADR 0035 through the real core app: the routes behind which the hub proxies the owner's feed, the classified calendar API, the assistant's answers ("What's on my calendar today?",
"Do I have meetings tomorrow?", "Am I on leave next week?") and the guarantee that the URL appears in nothing the app returns or logs. The fetcher is the real one with a mock transport and a
fake resolver, so the URL checks run for real."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.feed import CalendarFeedService, InMemoryFeedStore
from companion_core.calendar.reminders import due_reminders
from companion_core.calendar.safe_fetch import FeedFetcher
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient
from reachy_hub.app import create_app as create_hub_app

URL = "https://calendar.example.com/private/abcdef-secret-token/basic.ics"
OWNER = "owner@example.com"


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ")


def vevent(uid, *lines):
    return "BEGIN:VEVENT\nUID:" + uid + "\nDTSTAMP:20261001T000000Z\n" + "\n".join(lines) + "\nEND:VEVENT"


def relative_feed() -> bytes:
    """A feed built around the real today, in UTC (the default persona zone): meetings, an appointment, leave and a banner, so the assistant's answers can be checked on any day."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow, monday = today + timedelta(days=1), today - timedelta(days=today.weekday()) + timedelta(days=7)
    day = lambda d: d.strftime("%Y%m%d")
    people = (f"ATTENDEE;PARTSTAT=ACCEPTED:mailto:{OWNER}", "ATTENDEE;PARTSTAT=ACCEPTED:mailto:dev@example.com")
    events = [
        vevent("m-today", f"DTSTART:{stamp(today + timedelta(hours=14))}", f"DTEND:{stamp(today + timedelta(hours=15))}", "SUMMARY:Sprint planning", *people),
        vevent("a-today", f"DTSTART:{stamp(today + timedelta(hours=16))}", f"DTEND:{stamp(today + timedelta(hours=17))}", "SUMMARY:Dentist appointment"),
        vevent("l-today", f"DTSTART;VALUE=DATE:{day(today)}", f"DTEND;VALUE=DATE:{day(tomorrow)}", "SUMMARY:Day off"),
        vevent("p-today", f"DTSTART:{stamp(today + timedelta(hours=11))}", f"DTEND:{stamp(today + timedelta(hours=12))}", "CLASS:PRIVATE", "SUMMARY:Secret errand"),
        vevent("m-tomorrow-1", f"DTSTART:{stamp(tomorrow + timedelta(hours=9))}", f"DTEND:{stamp(tomorrow + timedelta(hours=10))}", "SUMMARY:Design review", *people),
        vevent("m-tomorrow-2", f"DTSTART:{stamp(tomorrow + timedelta(hours=13))}", f"DTEND:{stamp(tomorrow + timedelta(hours=14))}", "SUMMARY:Vendor call", "LOCATION:https://zoom.us/j/1"),
        vevent("a-tomorrow", f"DTSTART:{stamp(tomorrow + timedelta(hours=15))}", f"DTEND:{stamp(tomorrow + timedelta(hours=16))}", "SUMMARY:Dentist follow-up"),
        vevent("u-tomorrow", f"DTSTART:{stamp(tomorrow + timedelta(hours=17))}", f"DTEND:{stamp(tomorrow + timedelta(hours=18))}", "SUMMARY:Quiet hour"),
        vevent("c-tomorrow", f"DTSTART:{stamp(tomorrow + timedelta(hours=18))}", f"DTEND:{stamp(tomorrow + timedelta(hours=19))}", "STATUS:CANCELLED", "SUMMARY:Cancelled retro", *people),
        vevent("leave-next-week", f"DTSTART;VALUE=DATE:{day(monday)}", f"DTEND;VALUE=DATE:{day(monday + timedelta(days=3))}", "SUMMARY:Annual leave"),
        vevent("m-on-leave", f"DTSTART:{stamp(monday + timedelta(days=1, hours=10))}", f"DTEND:{stamp(monday + timedelta(days=1, hours=11))}", "SUMMARY:Incident review", *people),
    ]
    return ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\n" + "\n".join(events) + "\nEND:VCALENDAR\n").encode()


class World:
    def __init__(self, body: bytes, address="93.184.216.34"):
        self.body, self.address, self.requests = body, address, []
        async def resolve(host, port):
            return [self.address]
        def handler(request):
            self.requests.append(request)
            return httpx.Response(200, content=self.body, headers={"content-type": "text/calendar"})
        self.fetcher = FeedFetcher(resolver=resolve, transport=httpx.MockTransport(handler))
        self.service = CalendarFeedService(InMemoryFeedStore(), self.fetcher)


def make_client(world: World) -> TestClient:
    app = create_app(
        transport=httpx.ASGITransport(app=create_hub_app(run_heartbeat_task=False)),
        calendar_store=InMemoryCalendarStore(), calendar_feed_service=world.service, run_calendar_feed_loop=False,
        task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(embed_fn=lambda texts: [[1.0] + [0.0] * 15 for _ in texts]), email_store=InMemoryEmailStore(),
        email_send_fn=lambda draft: asyncio.sleep(0), confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False,
    )
    return TestClient(app)


@pytest.fixture
def world():
    return World(relative_feed())


@pytest.fixture
def client(world):
    with make_client(world) as c:
        assert c.put("/calendar/feed", json={"url": URL, "config": {"rules": {"owner_emails": [OWNER]}}}).status_code == 200
        yield c


def ask(client, text):
    reply = client.post("/conversation", json={"session_id": "s", "conversation_id": "c", "channel": "telegram", "text": text})
    assert reply.status_code == 200, reply.text
    return reply.json()


# --- the routes and the secret ---------------------------------------------------------------------------------------------------------------------------------

def test_setting_the_url_downloads_once_and_never_echoes_it(world, caplog):
    caplog.set_level(logging.DEBUG)
    with make_client(world) as client:
        response = client.put("/calendar/feed", json={"url": URL})
        body = response.json()
        assert response.status_code == 200 and body["configured"] and body["freshness"] == "fresh" and body["host"] == "calendar.example.com" and body["event_count"] > 5
        assert len(world.requests) == 1 and world.requests[0].url.path == "/private/abcdef-secret-token/basic.ics"
        everything = response.text + client.get("/calendar/feed").text + client.get("/calendar/meeting-reminders").text + caplog.text
        assert "secret-token" not in everything and "abcdef" not in everything


def test_an_unsafe_url_is_refused_with_a_fixed_code(world):
    world.address = "10.0.0.7"
    with make_client(world) as client:
        response = client.put("/calendar/feed", json={"url": URL})
        assert response.status_code == 400 and response.json() == {"detail": "unsafe_address"} and not world.requests
        assert client.get("/calendar/feed").json()["configured"] is False
        for bad in ("http://calendar.example.com/a.ics", "https://calendar.example.com:8443/a.ics", "file:///etc/passwd", "https://user:pw@calendar.example.com/a.ics"):
            refused = client.put("/calendar/feed", json={"url": bad})
            assert refused.status_code == 400 and refused.json() == {"detail": "unsafe_url"}


def test_unknown_fields_and_oversize_urls_are_rejected(client):
    assert client.put("/calendar/feed", json={"url": URL, "token": "x"}).status_code == 422
    assert client.put("/calendar/feed", json={"url": "https://a.example/" + "x" * 3000}).status_code == 422
    assert client.put("/calendar/feed", json={"config": {"lead_minutes": 0}}).status_code == 422
    assert client.put("/calendar/feed", json={"config": {"timezone": "Mars/Olympus"}}).status_code == 422


def test_settings_change_without_resending_the_url(client, world):
    before = len(world.requests)
    status = client.put("/calendar/feed", json={"config": {"lead_minutes": 10, "refresh_minutes": 30}}).json()
    assert status["config"]["lead_minutes"] == 10 and status["config"]["refresh_minutes"] == 30 and status["configured"] and len(world.requests) == before
    assert client.get("/calendar/meeting-reminders").json()["lead_minutes"] == 10


def test_refresh_and_clear(client, world):
    assert client.post("/calendar/feed/refresh").json()["freshness"] == "fresh" and len(world.requests) == 2
    cleared = client.delete("/calendar/feed").json()
    assert cleared["configured"] is False and cleared["event_count"] == 0 and client.get("/calendar/meeting-reminders").json()["reminders"] == []


def test_refresh_without_a_url_is_harmless():
    with make_client(World(b"")) as client:
        assert client.post("/calendar/feed/refresh").json()["configured"] is False


def test_overrides_through_the_api(client):
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    events = client.get("/calendar/events", params={"start": tomorrow.isoformat(), "end": (tomorrow + timedelta(days=1)).isoformat()}).json()
    quiet = next(e for e in events if e["title"] == "Quiet hour")
    assert quiet["classification"] == "unknown_timed" and quiet["remind"] is False
    assert client.put("/calendar/overrides", json={"key": quiet["event_key"], "classification": "meeting"}).status_code == 200
    again = next(e for e in client.get("/calendar/events", params={"start": tomorrow.isoformat(), "end": (tomorrow + timedelta(days=1)).isoformat()}).json() if e["title"] == "Quiet hour")
    assert again["classification"] == "meeting" and again["classification_basis"] == "owner" and again["remind"]
    assert client.request("DELETE", "/calendar/overrides", json={"key": quiet["event_key"]}).status_code == 200
    assert client.put("/calendar/overrides", json={"key": "not-a-feed-key", "classification": "meeting"}).status_code == 422
    assert client.put("/calendar/overrides", json={"key": quiet["event_key"], "classification": "important"}).status_code == 422


# --- the classified calendar API ------------------------------------------------------------------------------------------------------------------------------

def window(client, days_from=0, days=2, **params):
    start = (datetime.now(UTC) + timedelta(days=days_from)).replace(hour=0, minute=0, second=0, microsecond=0)
    return client.get("/calendar/events", params={"start": start.isoformat(), "end": (start + timedelta(days=days)).isoformat(), **params}).json()


def test_events_expose_classification_for_both_clients(client):
    events = {e["title"]: e for e in window(client)}
    assert events["Sprint planning"]["classification"] == "meeting" and events["Sprint planning"]["classification_basis"] == "explicit"
    assert events["Dentist appointment"]["classification"] == "personal_appointment"
    assert events["Day off"]["classification"] == "leave_or_ooo" and events["Day off"]["all_day"]
    assert events["Busy"]["classification"] == "busy_private" and events["Busy"]["redacted"] and events["Busy"]["location"] is None
    assert "Secret errand" not in str(events)
    assert all({"classification", "classification_reasons", "status", "all_day", "event_key", "series_key", "remind", "source"} <= set(e) for e in events.values())
    assert "Cancelled retro" not in events and "Cancelled retro" in {e["title"] for e in window(client, include_cancelled="true")}


def test_the_occupying_view_leaves_out_leave_banners_and_cancelled_events(client):
    occupying = {e["title"] for e in window(client, occupying="true")}
    assert {"Sprint planning", "Dentist appointment", "Busy", "Design review"} <= occupying  # a hidden entry still blocks the time
    assert "Day off" not in occupying and "Cancelled retro" not in occupying
    assert "Annual leave" not in {e["title"] for e in window(client, days_from=7, days=7, occupying="true")}


def test_the_hub_signal_for_an_event_in_progress_is_not_tripped_by_a_leave_day(client):
    """The hub keeps alarms and reminders quiet while an event is in progress (events_in_progress asks with occupying=true). A leave day is not such an event."""
    now = datetime.now(UTC).replace(hour=0, minute=1)
    probe = {"start": now.isoformat(), "end": (now + timedelta(seconds=1)).isoformat()}
    assert [e["title"] for e in client.get("/calendar/events", params=probe).json()] == ["Day off"]  # the plain list shows it
    assert client.get("/calendar/events", params={**probe, "occupying": "true"}).json() == []  # the hub's question does not


def test_the_meeting_reminders_payload(client):
    payload = client.get("/calendar/meeting-reminders", params={"hours": 168}).json()
    assert payload["lead_minutes"] == 5 and payload["feed"]["freshness"] == "fresh" and payload["snapshot_revision"]
    assert all(r["classification"] == "meeting" and r["event_key"].startswith("ics:") for r in payload["reminders"])
    assert "Dentist appointment" not in str(payload) and "Cancelled retro" not in str(payload) and "Annual leave" not in str(payload)


def test_legacy_channel_reminders_do_not_use_feed_events(world):
    now = datetime.now(UTC)
    body = ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\n" + vevent(
        "soon", f"DTSTART:{stamp(now + timedelta(minutes=10))}", f"DTEND:{stamp(now + timedelta(minutes=40))}", "SUMMARY:Imminent sync", f"ATTENDEE:mailto:{OWNER}", "ATTENDEE:mailto:x@example.com",
    ) + "\nEND:VCALENDAR\n").encode()
    other = World(body)
    with make_client(other) as client:
        client.put("/calendar/feed", json={"url": URL})
        assert any(e["title"] == "Imminent sync" for e in client.get("/calendar/events", params={"start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat()}).json())
        store = client.app.state.calendar_store
        assert asyncio.run(due_reminders(store, now, within_minutes=15)) == []
        assert client.get("/calendar/reminders/due").json() == []


# --- what the assistant says --------------------------------------------------------------------------------------------------------------------------------------

def test_today_differentiates_meetings_appointments_and_leave(client):
    reply = ask(client, "What's on my calendar today?")
    text = reply["reply"]
    assert reply["privacy"] == "work-private"
    assert "Meetings:" in text and "Sprint planning" in text
    assert "Appointments:" in text and "Dentist appointment" in text
    assert "Leave:" in text and "Day off" in text
    assert "Busy (details hidden):" in text and "Secret errand" not in text
    assert text.index("Meetings:") < text.index("Appointments:") < text.index("Leave:")


def test_meetings_tomorrow_returns_only_classified_meetings(client):
    text = ask(client, "Do I have meetings tomorrow?")["reply"]
    assert text.startswith("You have 2 meetings tomorrow:") and "Design review" in text and "Vendor call" in text
    assert "Dentist" not in text and "Cancelled" not in text and "Quiet hour" not in text
    assert "1 other timed event I couldn't tell was a meeting is not counted" in text  # honest about the unknown, does not guess


def test_an_unsupported_window_is_said_not_guessed(client):
    assert ask(client, "Do I have any meetings next month?")["reply"].startswith("I can only look at")
    assert ask(client, "Do I have meetings today and tomorrow?")["reply"].startswith("That names more than one time range")


def test_meetings_this_week_include_todays(client):
    text = ask(client, "Do I have meetings this week?")["reply"]
    assert text.startswith("You have") and "Sprint planning" in text


def test_leave_next_week_reports_the_whole_multi_day_span(client):
    reply = ask(client, "Am I on leave next week?")
    monday = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=datetime.now(UTC).weekday()) + timedelta(days=7)
    assert reply["reply"].startswith("Yes, you're on leave next week:") and "Annual leave" in reply["reply"]
    assert f"{monday:%a %d %b} to {monday + timedelta(days=2):%a %d %b}" in reply["reply"]  # three days; the exclusive end is not shown as a leave day
    assert reply["privacy"] == "work-private"


def test_no_leave_is_reported_as_no_leave(client):
    assert ask(client, "Am I on leave tomorrow?")["reply"] == "No leave is marked on your calendar tomorrow."


def test_a_leave_day_does_not_remove_meetings_scheduled_on_it(client):
    text = ask(client, "Do I have meetings next week?")["reply"]
    assert "Incident review" in text and text.startswith("You have 1 meeting next week:")


def test_a_stale_feed_is_said_in_the_answer(client, world):
    world.service._clock = lambda: datetime.now(UTC) + timedelta(hours=5)
    assert "last updated 5 hours ago" in ask(client, "Do I have meetings tomorrow?")["reply"]


def test_unrelated_meeting_requests_are_not_calendar_lookups(client):
    for text in ("Summarize the meeting", "start a meeting recording", "What did we decide in the meeting notes?", "Cancel my meeting tomorrow"):
        assert "Design review" not in ask(client, text)["reply"], text


# --- immediate synchronisation: upload and the one-revision schedule ----------------------------------------------------------------------------------------------

def ics_of(*events) -> bytes:
    return ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\n" + "\n".join(events) + "\nEND:VCALENDAR\n").encode()


def simple(uid, start, title, *extra):
    return vevent(uid, f"DTSTART:{stamp(start)}", f"DTEND:{stamp(start + timedelta(hours=1))}", f"SUMMARY:{title}", *extra)


def test_an_uploaded_file_replaces_the_source_at_once_and_is_visible_through_the_same_api(client):
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    people = (f"ATTENDEE:mailto:{OWNER}", "ATTENDEE:mailto:dev@example.com")
    body = ics_of(*[simple(f"u{i}", tomorrow + timedelta(hours=i * 2), f"Upload meeting {i}", *people) for i in range(5)])
    before = client.get("/calendar/feed").json()["generation"]
    response = client.put("/calendar/feed/upload", content=body, headers={"X-Filename": "C%3A%5Ctmp%5Cweek.ics", "Content-Type": "text/calendar"})
    status = response.json()
    assert response.status_code == 200 and status["source"] == "upload" and status["host"] == "week.ics" and status["event_count"] == 5 and status["generation"] == before + 1
    shown = window(client, days_from=1, days=1)
    assert [e["title"] for e in shown] == [f"Upload meeting {i}" for i in range(5)]  # the previous calendar's events are gone, these are in order
    assert client.get("/calendar/meeting-reminders", params={"hours": 168}).json()["snapshot_revision"] == status["snapshot_revision"]
    replaced = client.put("/calendar/feed/upload", content=ics_of(*[simple(f"u{i}", tomorrow + timedelta(hours=i * 2), f"Upload meeting {i}", *people) for i in range(3)])).json()
    assert replaced["event_count"] == 3 and [e["title"] for e in window(client, days_from=1, days=1)] == [f"Upload meeting {i}" for i in range(3)]


def test_a_bad_upload_is_refused_with_a_fixed_code_and_changes_nothing_but_the_error(client):
    good = client.get("/calendar/feed").json()
    for body in (b"BEGIN:VCALENDAR\nbroken secret-token-xyz", b"<html></html>", b"\xff\xfe\x00\x00"):
        refused = client.put("/calendar/feed/upload", content=body)
        assert refused.status_code == 400 and refused.json() == {"detail": "not_calendar"} and "secret-token" not in refused.text
    after = client.get("/calendar/feed").json()
    assert after["generation"] == good["generation"] and after["snapshot_revision"] == good["snapshot_revision"] and after["error"] == "not_calendar" and after["sync_state"] == "error"
    assert after["event_count"] == good["event_count"] > 0 and any(e["title"] == "Sprint planning" for e in window(client))  # the last valid calendar is still served
    too_big = client.put("/calendar/feed/upload", content=b"BEGIN:VCALENDAR\n" + b"X-A:" + b"a" * (10 * 1024 * 1024) + b"\nEND:VCALENDAR\n")
    assert too_big.status_code == 400 and too_big.json() == {"detail": "too_large"}


def test_a_valid_empty_calendar_clears_the_events_and_the_reminders(client):
    empty = client.put("/calendar/feed/upload", content=ics_of()).json()
    assert empty["error"] is None and empty["sync_state"] == "ok" and empty["event_count"] == 0
    assert window(client) == [] and client.get("/calendar/meeting-reminders", params={"hours": 168}).json()["reminders"] == []


def test_the_schedule_is_one_revision_in_chronological_order_with_both_clocks(client):
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    response = client.get("/calendar/schedule", params={"start": start.isoformat(), "end": (start + timedelta(days=9)).isoformat()})
    view = response.json()
    assert response.status_code == 200 and view["generation"] == view["feed"]["generation"] == client.get("/calendar/feed").json()["generation"]
    assert view["snapshot_revision"] == view["feed"]["snapshot_revision"] and view["feed"]["sync_state"] == "ok" and view["feed"]["source"] == "url"
    starts = [e["start"] for e in view["events"]]
    assert starts == sorted(starts) and {e["classification"] for e in view["events"]} >= {"meeting", "leave_or_ooo", "busy_private", "personal_appointment"}
    assert view["feed"]["last_success_at"] and view["feed"]["last_attempt_at"] and "secret-token" not in response.text
    busy = next(e for e in view["events"] if e["classification"] == "busy_private")
    assert busy["title"] == "Busy" and busy["location"] is None and busy["redacted"] and "Secret errand" not in response.text
