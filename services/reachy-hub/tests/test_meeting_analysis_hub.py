"""Phase 31 through the hub: the owner-only proxy (owner session plus CSRF, no bearer path, no non-owner session, fixed errors), the flag-off behaviour, and the whole chain
hub -> real core app with a scripted local model. In-process; nothing is deployed."""

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from companion_core.app import create_app as create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meeting_analysis.store import InMemoryMeetingAnalysisStore
from companion_core.meetings.models import Meeting, MeetingJobStatus
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
LINE = "Alice will contact the vendor about compatibility by Friday."


def build(monkeypatch, *, enabled=True):
    (monkeypatch.setenv("MEETING_ANALYSIS_ENABLED", "true") if enabled else monkeypatch.delenv("MEETING_ANALYSIS_ENABLED", raising=False))
    tasks, planner, meetings = InMemoryTaskStore(), InMemoryPlannerStore(), InMemoryMeetingStore()
    meeting = Meeting(title="Sync", source_filename="a.wav", content_type="audio/wav", audio_path="/nonexistent", started_at=datetime(2026, 10, 9, 14, 0, tzinfo=UTC),
                      status=MeetingJobStatus.COMPLETE, transcript_segments=[{"start": 0.0, "end": 5.0, "text": LINE}], aligned_segments=[{"start": 0.0, "end": 5.0, "text": LINE, "speaker": "SPEAKER_00"}])
    meetings._meetings[meeting.id] = meeting

    async def provider():
        async def ask(messages, max_tokens):
            return json.dumps({"items": [{"type": "action", "text": "Contact the vendor about compatibility", "evidence": [{"segment": 0, "quote": "Alice will contact the vendor about compatibility"}],
                                          "assignee": "Alice", "stated_time": "by Friday"}]})

        return ask, "scripted-7b"

    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=tasks, planner_store=planner, meeting_store=meetings, run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, meeting_analysis_store=InMemoryMeetingAnalysisStore() if enabled else None, meeting_analysis_provider=provider, run_meeting_analysis_runner=False)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    hub = TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token",
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core))))
    return hub, core, tasks, meeting


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200


ROUTES = [("get", "/meeting-analysis/config", None), ("get", "/meetings/abc/analysis", None), ("post", "/meetings/abc/analysis", {}), ("post", "/meeting-analysis/runs/abc/retry", {}),
          ("get", "/meeting-analysis/items", None), ("post", "/meeting-analysis/items/abc/accept", {}), ("post", "/meeting-analysis/items/abc/dismiss", {}),
          ("get", "/meeting-analysis/provenance/abc", None)]
CHANGES = [r for r in ROUTES if r[0] != "get"]


def call(client, method, path, body, headers=None):
    return getattr(client, method)(path, headers=headers or {}, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_no_login_and_a_bearer_token_alone_are_refused_on_every_route(monkeypatch, method, path, body):
    hub, core, tasks, meeting = build(monkeypatch)
    with hub:
        assert call(hub, method, path.replace("abc", meeting.id), body, CSRF).status_code == 401
        assert call(hub, method, path.replace("abc", meeting.id), body, {**BEARER, **CSRF}).status_code == 401  # a robot-control credential must not analyse, confirm or dismiss
    assert core.state.meeting_analysis_store._runs == {} and asyncio.run(tasks.list_tasks()) == []


def test_a_session_for_someone_who_is_not_the_owner_is_refused(monkeypatch):
    hub, core, _tasks, meeting = build(monkeypatch)
    with hub:
        login(hub)
        assert hub.get("/meeting-analysis/config").status_code == 200

        async def someone_else():
            return "intruder"

        real = hub.app.state.user_store.owner
        hub.app.state.user_store.owner = someone_else
        assert call(hub, "post", f"/meetings/{meeting.id}/analysis", {}, CSRF).status_code == 401
        assert call(hub, "get", "/meeting-analysis/items", None, CSRF).status_code == 401
        hub.app.state.user_store.owner = real
    assert core.state.meeting_analysis_store._runs == {}


@pytest.mark.parametrize(("method", "path", "body"), CHANGES)
def test_every_change_needs_the_csrf_header_even_for_the_owner(monkeypatch, method, path, body):
    hub, core, tasks, meeting = build(monkeypatch)
    with hub:
        login(hub)
        assert call(hub, method, path.replace("abc", meeting.id), body).status_code == 403
    assert core.state.meeting_analysis_store._runs == {} and asyncio.run(tasks.list_tasks()) == []


def test_the_owner_runs_the_whole_flow_through_the_hub_and_errors_leak_nothing(monkeypatch):
    hub, core, tasks, meeting = build(monkeypatch)
    with hub:
        login(hub)
        assert hub.get("/meeting-analysis/config").json() == {"enabled": True}
        assert hub.get(f"/meetings/{meeting.id}/analysis").json()["state"] == "not_analysed"
        queued = hub.post(f"/meetings/{meeting.id}/analysis", json={}, headers=CSRF).json()
        assert queued["state"] == "queued" and queued["created"] is True and LINE not in json.dumps(queued)
        with TestClient(core) as _:
            pass
        assert asyncio.run(core.state.meeting_analysis_service.process_next()) is True
        status = hub.get(f"/meetings/{meeting.id}/analysis").json()
        assert status["state"] == "review_required" and status["items"][0]["evidence"][0]["segment"] == 0
        assert asyncio.run(tasks.list_tasks()) == []  # not a task yet
        iid = status["items"][0]["id"]
        done = hub.post(f"/meeting-analysis/items/{iid}/accept", json={}, headers=CSRF).json()
        again = hub.post(f"/meeting-analysis/items/{iid}/accept", json={}, headers=CSRF).json()
        assert done["record"] == again["record"] and len(asyncio.run(tasks.list_tasks())) == 1
        assert hub.get(f"/meeting-analysis/provenance/{done['record']['id']}").json()["meeting_id"] == meeting.id
        assert hub.get("/meeting-analysis/items").json() == {"items": []}
        missing = hub.post("/meeting-analysis/items/nope/accept", json={}, headers=CSRF)
        assert missing.status_code == 404 and missing.json()["detail"] == "No such item"
        bad = hub.post(f"/meeting-analysis/items/{iid}/accept", json={"unknown": 1}, headers=CSRF)
        assert bad.status_code == 422 and "vendor" not in bad.text


def test_with_the_feature_off_the_config_says_so_and_the_rest_is_404(monkeypatch):
    hub, _core, _tasks, meeting = build(monkeypatch, enabled=False)
    with hub:
        login(hub)
        assert hub.get("/meeting-analysis/config").json() == {"enabled": False}
        assert hub.get(f"/meetings/{meeting.id}/analysis").status_code == 404
        assert hub.post(f"/meetings/{meeting.id}/analysis", json={}, headers=CSRF).status_code == 404
