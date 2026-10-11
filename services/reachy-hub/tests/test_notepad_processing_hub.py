"""Phase 49 through the hub: the owner-only proxy (owner session plus CSRF, no bearer path, no non-owner session, fixed errors), the flag-off behaviour, and the whole chain
hub -> real core app with a scripted local model. In-process; nothing is deployed."""

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
from companion_core.notepad_processing.store import InMemoryNotepadStore
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
LINE = "Renew the lab safety certificate before it lapses."
BODY = f"{LINE}\nThe lab wifi password rotates monthly."


def build(monkeypatch, *, enabled=True):
    (monkeypatch.setenv("NOTEPAD_PROCESSING_ENABLED", "true") if enabled else monkeypatch.delenv("NOTEPAD_PROCESSING_ENABLED", raising=False))
    store, tasks, planner = InMemoryNotepadStore(), InMemoryTaskStore(), InMemoryPlannerStore()

    async def provider():
        async def ask(messages, max_tokens):
            return json.dumps({"items": [{"type": "task", "text": "Renew the lab safety certificate", "evidence": [LINE], "stated_time": None, "about_owner": True, "ambiguities": []}]})

        return ask, "scripted-7b"

    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=tasks, planner_store=planner, meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, notepad_store=store if enabled else None, notepad_provider=provider, run_notepad_runner=False)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    hub = TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token",
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core))))
    return hub, core, store, tasks, planner


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200


def make_note(planner, body=BODY, title="Tasks for next week"):
    return asyncio.run(planner.add_note(title, body))


ROUTES = [("get", "/notepad-processing/config", None), ("get", "/notes/abc/processing", None), ("post", "/notes/abc/processing", {}), ("get", "/notes/abc/meeting-links", None),
          ("put", "/notes/abc/meeting-links/m1", {"state": "confirmed"}), ("post", "/notepad-processing/jobs/abc/retry", {}), ("get", "/notepad-proposals", None),
          ("post", "/notepad-proposals/abc/accept", {}), ("post", "/notepad-proposals/abc/dismiss", {})]
CHANGES = [r for r in ROUTES if r[0] != "get"]


def call(client, method, path, body, headers=None):
    return getattr(client, method)(path, headers=headers or {}, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_no_login_and_a_bearer_token_alone_are_refused_on_every_route(monkeypatch, method, path, body):
    hub, _core, store, tasks, planner = build(monkeypatch)
    note = make_note(planner)
    with hub:
        assert call(hub, method, path.replace("abc", note.id), body, CSRF).status_code == 401
        assert call(hub, method, path.replace("abc", note.id), body, {**BEARER, **CSRF}).status_code == 401  # a robot-control credential must not enqueue, accept or link
    assert store._jobs == {} and asyncio.run(tasks.list_tasks()) == []


def test_a_session_for_someone_who_is_not_the_owner_is_refused(monkeypatch):
    hub, _core, store, _tasks, planner = build(monkeypatch)
    note = make_note(planner)
    with hub:
        login(hub)
        assert hub.get("/notepad-processing/config").status_code == 200

        async def someone_else():
            return "intruder"

        real = hub.app.state.user_store.owner
        hub.app.state.user_store.owner = someone_else
        assert call(hub, "post", f"/notes/{note.id}/processing", {}, CSRF).status_code == 401
        assert call(hub, "get", "/notepad-proposals", None, CSRF).status_code == 401
        hub.app.state.user_store.owner = real
    assert store._jobs == {}


@pytest.mark.parametrize(("method", "path", "body"), CHANGES)
def test_every_change_needs_the_csrf_header_even_for_the_owner(monkeypatch, method, path, body):
    hub, _core, store, tasks, planner = build(monkeypatch)
    note = make_note(planner)
    with hub:
        login(hub)
        assert call(hub, method, path.replace("abc", note.id), body).status_code == 403
    assert store._jobs == {} and asyncio.run(tasks.list_tasks()) == []


def test_the_owner_runs_the_whole_flow_through_the_hub_and_errors_leak_nothing(monkeypatch):
    hub, core, _store, tasks, planner = build(monkeypatch)
    note = make_note(planner)
    with hub:
        login(hub)
        assert hub.get("/notepad-processing/config").json() == {"enabled": True}
        assert hub.get(f"/notes/{note.id}/processing").json()["state"] == "not_processed"
        queued = hub.post(f"/notes/{note.id}/processing", json={}, headers=CSRF).json()
        assert queued["state"] == "queued" and queued["created"] is True
        with TestClient(core) as _:
            pass
        assert asyncio.run(core.state.notepad_service.process_next()) is True
        status = hub.get(f"/notes/{note.id}/processing").json()
        assert status["state"] == "review_required" and status["proposals"][0]["evidence"] == LINE
        assert asyncio.run(tasks.list_tasks()) == []  # not authoritative yet
        pid = status["proposals"][0]["id"]
        done = hub.post(f"/notepad-proposals/{pid}/accept", json={}, headers=CSRF).json()
        again = hub.post(f"/notepad-proposals/{pid}/accept", json={}, headers=CSRF).json()
        assert done["record"] == again["record"] and len(asyncio.run(tasks.list_tasks())) == 1
        assert hub.get("/notepad-proposals").json() == {"proposals": []}
        missing = hub.post("/notepad-proposals/nope/accept", json={}, headers=CSRF)
        assert missing.status_code == 404 and missing.json()["detail"] == "No such proposal"
        bad = hub.post(f"/notepad-proposals/{pid}/accept", json={"unknown": 1}, headers=CSRF)
        assert bad.status_code == 422 and "lab" not in bad.text
        assert hub.get("/notes/not a valid id/processing").status_code in (404, 422)


def test_links_go_through_the_hub_and_unlinking_keeps_the_note(monkeypatch):
    hub, _core, _store, _tasks, planner = build(monkeypatch)
    note = make_note(planner)
    with hub:
        login(hub)
        assert hub.get(f"/notes/{note.id}/meeting-links").json() == {"note_id": note.id, "links": []}
        assert hub.put(f"/notes/{note.id}/meeting-links/nope", json={"state": "confirmed"}, headers=CSRF).status_code == 404
        assert hub.put(f"/notes/{note.id}/meeting-links/nope", json={"state": "bogus"}, headers=CSRF).status_code == 422
    assert asyncio.run(planner.get_note(note.id)).body == BODY


def test_with_the_feature_off_the_hub_reports_it_and_the_rest_is_404(monkeypatch):
    hub, _core, _store, _tasks, planner = build(monkeypatch, enabled=False)
    note = make_note(planner)
    with hub:
        login(hub)
        assert hub.get("/notepad-processing/config").json() == {"enabled": False}
        assert hub.post(f"/notes/{note.id}/processing", json={}, headers=CSRF).status_code == 404
        assert hub.get("/notepad-proposals").status_code == 404
        assert hub.put(f"/planner/notes/{note.id}", json={"title": "t", "body": "b"}, headers=CSRF).status_code == 200  # ordinary note editing is untouched
