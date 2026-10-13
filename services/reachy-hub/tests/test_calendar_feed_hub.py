"""ADR 0035 through the hub: the owner-only proxy for the calendar feed (owner session plus CSRF, no bearer path, no non-owner session, fixed errors that never quote the URL) and the whole
chain hub -> real core app with a mock feed. Also: the hub's "is an event in progress" question must not count a leave day. In-process; nothing is deployed."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from companion_core.app import create_app as create_core_app
from companion_core.calendar.feed import CalendarFeedService, InMemoryFeedStore
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
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

CSRF = {"X-Reachy-CSRF": "1"}
BEARER = {"Authorization": "Bearer test-token"}
URL = "https://calendar.example.com/private/abcdef-secret-token/basic.ics"
FIXTURE = (Path(__file__).resolve().parents[2] / "companion-core" / "tests" / "fixtures" / "calendar" / "work-calendar.ics").read_bytes()


def build(address="93.184.216.34"):
    requests = []
    async def resolve(host, port):
        return [address]
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=FIXTURE)
    service = CalendarFeedService(InMemoryFeedStore(), FeedFetcher(resolver=resolve, transport=httpx.MockTransport(handler)))
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), calendar_feed_service=service, run_calendar_feed_loop=False, task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    hub = TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token",
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core))))
    return hub, core, service, requests


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200


WHEN = {"start": "2026-10-12T00:00:00+00:00", "end": "2026-10-18T00:00:00+00:00"}
ROUTES = [("get", "/calendar-feed", None), ("put", "/calendar-feed", {"url": URL}), ("delete", "/calendar-feed", None), ("post", "/calendar-feed/refresh", {}),
          ("put", "/calendar-feed/overrides", {"key": "ics:abcde", "classification": "meeting"}), ("get", "/calendar-feed/reminders", None), ("get", "/calendar-feed/events?" + "&".join(f"{k}={v}" for k, v in WHEN.items()).replace("+", "%2B"), None)]
CHANGES = [r for r in ROUTES if r[0] != "get"]


def call(client, method, path, body, headers=None):
    return client.request(method.upper(), path, headers=headers or {}, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_no_login_and_a_bearer_token_alone_are_refused_on_every_route(method, path, body):
    hub, _core, service, requests = build()
    with hub:
        assert call(hub, method, path, body, CSRF).status_code == 401
        assert call(hub, method, path, body, {**BEARER, **CSRF}).status_code == 401  # a robot-control credential must not read or replace the owner's feed
    assert not requests and asyncio.run(service.status())["configured"] is False


@pytest.mark.parametrize(("method", "path", "body"), CHANGES)
def test_every_change_needs_the_csrf_header_even_for_the_owner(method, path, body):
    hub, _core, service, requests = build()
    with hub:
        login(hub)
        assert call(hub, method, path, body).status_code == 403
    assert not requests and asyncio.run(service.status())["configured"] is False


def test_a_session_for_someone_who_is_not_the_owner_is_refused():
    hub, _core, service, _requests = build()
    with hub:
        login(hub)
        assert hub.get("/calendar-feed").status_code == 200

        async def someone_else():
            return "intruder"

        real = hub.app.state.user_store.owner
        hub.app.state.user_store.owner = someone_else
        assert call(hub, "put", "/calendar-feed", {"url": URL}, CSRF).status_code == 401
        assert call(hub, "get", "/calendar-feed/reminders", None).status_code == 401
        hub.app.state.user_store.owner = real
    assert asyncio.run(service.status())["configured"] is False


def test_the_owner_sets_the_feed_and_reads_it_back_without_the_url(caplog):
    caplog.set_level(logging.DEBUG)
    hub, _core, _service, requests = build()
    with hub:
        login(hub)
        put = hub.put("/calendar-feed", json={"url": URL, "config": {"rules": {"owner_emails": ["owner@example.com"]}, "device_horizon_hours": 168}}, headers=CSRF)
        assert put.status_code == 200 and put.json()["configured"] and put.json()["freshness"] == "fresh" and put.json()["host"] == "calendar.example.com"
        assert requests[0].url.path == "/private/abcdef-secret-token/basic.ics"
        reminders = hub.get("/calendar-feed/reminders", params={"hours": 168}).json()
        events = hub.get("/calendar-feed/events", params=WHEN).json()
        status = hub.get("/calendar-feed").json()
        assert hub.get("/calendar-feed").headers["cache-control"] == "no-store"
        body = " ".join([put.text, str(reminders), str(events), str(status), caplog.text])
        assert "secret-token" not in body and "abcdef" not in body
        assert any(e["classification"] == "personal_appointment" for e in events) and all("classification" in e for e in events)
        assert all(r["classification"] == "meeting" for r in reminders["reminders"])
        assert hub.put("/calendar-feed/overrides", json={"key": events[0]["event_key"], "classification": "unknown_timed"}, headers=CSRF).status_code == 200
        assert hub.delete("/calendar-feed", headers=CSRF).json()["configured"] is False


def test_errors_are_fixed_codes_that_never_quote_the_url():
    hub, _core, _service, requests = build(address="10.1.2.3")
    with hub:
        login(hub)
        refused = hub.put("/calendar-feed", json={"url": URL}, headers=CSRF)
        assert refused.status_code == 400 and refused.json() == {"detail": "unsafe_address"} and not requests
        plain = hub.put("/calendar-feed", json={"url": "http://calendar.example.com/private/abcdef-secret-token/a.ics"}, headers=CSRF)
        assert plain.status_code == 400 and plain.json() == {"detail": "unsafe_url"}
        long = hub.put("/calendar-feed", json={"url": "https://calendar.example.com/" + "secret-token" * 400}, headers=CSRF)
        assert long.status_code == 422 and long.json() == {"detail": "invalid_request"} and "secret-token" not in long.text
        bad_config = hub.put("/calendar-feed", json={"config": {"lead_minutes": 0}}, headers=CSRF)
        assert bad_config.status_code == 422 and bad_config.json() == {"detail": "invalid_request"}
        unknown = hub.put("/calendar-feed", json={"url": URL, "token": "x"}, headers=CSRF)
        assert unknown.status_code == 422 and "secret-token" not in unknown.text.replace("abcdef-secret-token", "")


def test_the_owner_can_change_settings_and_override_a_classification_through_the_hub():
    hub, _core, service, requests = build()
    with hub:
        login(hub)
        hub.put("/calendar-feed", json={"url": URL}, headers=CSRF)
        before = len(requests)
        assert hub.put("/calendar-feed", json={"config": {"lead_minutes": 12}}, headers=CSRF).json()["config"]["lead_minutes"] == 12 and len(requests) == before
        assert hub.get("/calendar-feed/reminders").json()["lead_minutes"] == 12
        assert hub.put("/calendar-feed/overrides", json={"key": "nope", "classification": "meeting"}, headers=CSRF).status_code == 422
        assert hub.request("DELETE", "/calendar-feed/overrides", json={"key": "ics:abcdef"}, headers=CSRF).status_code == 200
        assert asyncio.run(service.status())["overrides"] == {}


def test_the_hubs_event_in_progress_question_asks_for_occupying_events_only():
    seen = []
    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[])
    client = CompanionCoreClient("http://core", transport=httpx.MockTransport(handler))
    asyncio.run(client.events_in_progress(datetime(2026, 10, 19, 4, 0, tzinfo=UTC)))
    assert seen[0]["occupying"] == "true"


def test_a_leave_day_does_not_make_the_owner_occupied_but_a_timed_event_does():
    """The path the alarm and reminder delivery really takes: the hub asks core for events in progress (occupying only) and treats any as 'occupied'."""
    hub, core, service, _requests = build()
    with hub:
        login(hub)
        hub.put("/calendar-feed", json={"url": URL, "config": {"rules": {"owner_emails": ["owner@example.com"]}}}, headers=CSRF)
        client = CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core))
        leave_midday = datetime(2026, 10, 20, 4, 0, tzinfo=UTC)  # inside "Annual leave" (19-21 Oct) and in no meeting
        meeting_now = datetime(2026, 10, 20, 7, 10, tzinfo=UTC)  # 15:10 in Singapore, inside "Incident review" 15:00-15:30
        assert asyncio.run(client.events_in_progress(leave_midday)) == []
        in_meeting = asyncio.run(client.events_in_progress(meeting_now))
        assert [e["title"] for e in in_meeting] == ["Incident review"]
        plain = asyncio.run(client._client.get("/calendar/events", params={"start": leave_midday.isoformat(), "end": (leave_midday + timedelta(seconds=1)).isoformat()}))
        assert [e["title"] for e in plain.json()] == ["Annual leave"]  # without occupying, the leave day would have blocked delivery all day
