"""Home through the hub (docs/phase-51.md): the owner-only proxy (owner session, CSRF for the POST, no bearer path, fixed errors) and the whole chain hub -> real core app. In process."""

import asyncio
import json

import httpx
import pytest
from companion_core.app import create_app as create_core_app
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


def build(transport=None):
    tasks = InMemoryTaskStore()
    asyncio.run(tasks.add_task("Write the report"))
    asyncio.run(tasks.add_task("Private salary memo", sensitivity="sensitive"))

    async def provider():
        async def ask(messages, max_tokens):
            return "You have 1 open task."

        return ask, "scripted"

    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=tasks, planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, notepad_provider=provider)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    return TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token",
        companion_core_client=CompanionCoreClient("http://core", transport=transport or httpx.ASGITransport(app=core)))), core


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200


ROUTES = [("get", "/home", None), ("get", "/home?sections=tasks", None), ("post", "/home/brief", {})]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_no_login_and_a_bearer_token_alone_are_refused(method, path, body):
    hub, _ = build()
    with hub:
        for headers in (CSRF, {**BEARER, **CSRF}):
            assert getattr(hub, method)(path, headers=headers, **({"json": body} if body is not None else {})).status_code == 401


def test_the_brief_needs_the_csrf_header_even_for_the_owner():
    hub, _ = build()
    with hub:
        login(hub)
        assert hub.post("/home/brief", json={}).status_code == 403


def test_the_owner_reads_home_and_the_brief_through_the_hub_without_sensitive_records():
    hub, _ = build()
    with hub:
        login(hub)
        home = hub.get("/home")
        assert home.status_code == 200 and home.headers["cache-control"] == "no-store"
        body = home.json()
        assert body["tasks"]["total"] == 1 and "salary" not in json.dumps(body).lower()  # the hub sends no ceiling: core's default is work-private
        assert body["schedule"]["status"] == "empty" and body["reviews"]["status"] == "off" and body["weather"]["status"] == "not_configured"
        only = hub.get("/home", params={"sections": "tasks,reminders"}).json()
        assert set(only["sources"]) == {"tasks", "reminders"}
        brief = hub.post("/home/brief", json={}, headers=CSRF).json()
        assert brief["mode"] == "generated" and brief["narrative"] == "You have 1 open task." and brief["lines"]
        assert hub.post("/home/brief", json={"narrative": False}, headers=CSRF).json()["mode"] == "deterministic"
        assert hub.get("/home", params={"sections": "bogus"}).status_code in (422,)
        assert hub.post("/home/brief", json={"surprise": 1}, headers=CSRF).status_code == 422


def test_a_core_outage_is_a_fixed_error_that_leaks_nothing():
    def down(request):
        raise httpx.ConnectError("core says: Private salary memo")

    hub, _ = build(httpx.MockTransport(down))
    with hub:
        login(hub)
        failed = hub.get("/home")
        assert failed.status_code == 502 and failed.json() == {"detail": "Home unavailable"}
