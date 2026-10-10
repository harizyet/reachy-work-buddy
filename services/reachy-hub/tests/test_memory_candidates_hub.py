"""Phase 44F through the hub: the owner-only review proxy (owner session plus CSRF, no bearer path, no cross-owner access, fixed errors), the full chain to a real core app, and the privacy-state
read companion-core uses before it may capture. In-process; nothing is deployed."""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from companion_core.app import create_app as create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory import candidate_service as cs
from companion_core.memory.candidates import InMemoryCandidateStore, new_candidate
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.secrets import Keyring
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry, Robot
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

from shared.models.memory import MemoryType
from shared.models.response import Privacy

CSRF = {"X-Reachy-CSRF": "1"}
BEARER = {"Authorization": "Bearer test-token"}
SECRET_TEXT = "I prefer zebra-striped canary notebooks."


def build(monkeypatch, *, enabled=True):
    (monkeypatch.setenv(cs.ENABLED_FLAG, "true") if enabled else monkeypatch.delenv(cs.ENABLED_FLAG, raising=False))
    monkeypatch.delenv(cs.CAPTURE_FLAG, raising=False)
    store, memory = InMemoryCandidateStore(), InMemoryMemoryStore()
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=memory, rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        memory_candidate_store=store)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    registry = InMemoryRobotRegistry()
    hub = TestClient(create_app(
        user_store=users, registry=registry, session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token",
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core))))
    return hub, core, store, memory, registry


def seed(store, text=SECRET_TEXT):
    digester = cs.KeyedDigester(Keyring("one", {"one": b"\x01" * 32}))
    k, d = digester.active(text)
    c = new_candidate(text=text, rule_id="preference.prefer", rule_version=1, conversation_id="c1", session_id="s", turn_index=1, channel="web", proposed_type=MemoryType.PROFILE,
                      proposed_scope=None, sensitivity=Privacy.WORK_PRIVATE, digest=d, digest_key_id=k, now=datetime.now(UTC))
    return asyncio.run(store.create(c, digester.lookup(text)))[0]


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200


ROUTES = [("get", "/memory-candidates", None), ("post", "/memory-candidates/abc/accept", {}), ("post", "/memory-candidates/abc/reject", {}),
          ("post", "/memory-candidates/forget-conversation", {"conversation_id": "c1"})]


def call(client, method, path, body, headers=None):
    return getattr(client, method)(path, headers=headers or {}, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_no_login_and_a_bearer_token_alone_are_refused_on_every_route(monkeypatch, method, path, body):
    hub, _core, store, memory, _ = build(monkeypatch)
    c = seed(store)
    with hub:
        assert call(hub, method, path, body, CSRF).status_code == 401
        assert call(hub, method, path, body, {**BEARER, **CSRF}).status_code == 401  # REMOTE_UI_TOKEN is a robot credential: not accepted for personal memory
    assert asyncio.run(store.get(c.id)).text == SECRET_TEXT and asyncio.run(memory.list_memories()) == []


def test_a_session_for_someone_who_is_not_the_owner_is_refused(monkeypatch):
    hub, _core, store, memory, _ = build(monkeypatch)
    c = seed(store)
    with hub:
        login(hub)
        assert hub.get("/memory-candidates").status_code == 200
        real = hub.app.state.user_store.owner

        async def someone_else():
            return "intruder"

        hub.app.state.user_store.owner = someone_else  # the session cookie now belongs to a user who is no longer the owner
        for method, path, body in [("get", "/memory-candidates", None), ("post", f"/memory-candidates/{c.id}/accept", {})]:
            assert call(hub, method, path, body, CSRF).status_code == 401
        hub.app.state.user_store.owner = real
    assert asyncio.run(memory.list_memories()) == []


@pytest.mark.parametrize(("method", "path", "body"), ROUTES[1:])
def test_every_change_needs_the_csrf_header_even_for_the_owner(monkeypatch, method, path, body):
    hub, _core, store, memory, _ = build(monkeypatch)
    c = seed(store)
    with hub:
        login(hub)
        assert call(hub, method, path.replace("abc", c.id), body).status_code == 403
    assert asyncio.run(memory.list_memories()) == [] and asyncio.run(store.get(c.id)).status.value == "pending"


def test_the_owner_reviews_end_to_end_through_the_hub_and_nothing_leaks_in_errors(monkeypatch):
    hub, _core, store, memory, _ = build(monkeypatch)
    a, b, c = seed(store), seed(store, "I always take notes by hand."), seed(store, "From now on keep answers short.")
    with hub:
        login(hub)
        listed = hub.get("/memory-candidates")
        assert listed.status_code == 200 and listed.headers["cache-control"] == "no-store"
        assert {x["text"] for x in listed.json()["candidates"]} == {SECRET_TEXT, "I always take notes by hand.", "From now on keep answers short."}
        done = hub.post(f"/memory-candidates/{a.id}/accept", json={"text": "I prefer zebra notebooks.", "expires_in_days": 30}, headers=CSRF)
        assert done.status_code == 200 and done.json()["candidate"]["status"] == "edited-accepted" and done.json()["memory"]["expires_at"] is not None
        assert hub.post(f"/memory-candidates/{a.id}/accept", json={}, headers=CSRF).json()["memory"]["id"] == done.json()["memory"]["id"]  # a double click
        rej = hub.post(f"/memory-candidates/{b.id}/reject", json={"suppress": True}, headers=CSRF).json()["candidate"]
        assert rej["status"] == "suppressed" and rej["text"] is None
        assert hub.post("/memory-candidates/forget-conversation", json={"conversation_id": "c1"}, headers=CSRF).json() == {"deleted": 1}
        refused = [hub.post(f"/memory-candidates/{b.id}/accept", json={}, headers=CSRF), hub.post("/memory-candidates/no-such/accept", json={}, headers=CSRF),
                   hub.post(f"/memory-candidates/{c.id}/accept", json={"text": "x" * 500}, headers=CSRF), hub.post(f"/memory-candidates/{a.id}/reject", json={}, headers=CSRF)]
        assert [r.status_code for r in refused] == [409, 404, 422, 409]
        assert all("zebra" not in r.text.lower() and "notes by hand" not in r.text for r in refused)
        assert hub.get("/memory-candidates").json()["candidates"] == []
    assert len(asyncio.run(memory.list_memories())) == 1


def test_validation_is_strict_and_a_bad_id_never_reaches_core(monkeypatch):
    hub, _core, store, _memory, _ = build(monkeypatch)
    c = seed(store)
    with hub:
        login(hub)
        for path, body in [(f"/memory-candidates/{c.id}/accept", {"bogus": 1}), (f"/memory-candidates/{c.id}/accept", {"type": "other"}), (f"/memory-candidates/{c.id}/accept", {"sensitivity": "secret"}),
                           (f"/memory-candidates/{c.id}/accept", {"expires_in_days": 0}), (f"/memory-candidates/{c.id}/reject", {"suppress": "maybe"}),
                           ("/memory-candidates/forget-conversation", {}), ("/memory-candidates/bad id!/accept", {}), ("/memory-candidates/" + "a" * 80 + "/reject", {})]:
            assert hub.post(path, json=body, headers=CSRF).status_code in (404, 422), path
    assert asyncio.run(store.get(c.id)).text == SECRET_TEXT


def test_with_the_core_flag_off_the_hub_reports_not_found_and_nothing_exists(monkeypatch):
    hub, _core, _store, _memory, _ = build(monkeypatch, enabled=False)
    with hub:
        login(hub)
        assert hub.get("/memory-candidates").status_code == 404
        assert hub.post("/memory-candidates/x/accept", json={}, headers=CSRF).status_code == 404


def test_the_privacy_state_read_is_authenticated_and_fails_toward_privacy(monkeypatch):
    hub, _core, _store, _memory, registry = build(monkeypatch)
    with hub:
        assert hub.get("/privacy/state").status_code == 401
        assert hub.get("/privacy/state", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert hub.get("/privacy/state", headers=BEARER).json() == {"privacy_mode": True, "robots": 0}  # no robot listening: privacy mode on
        asyncio.run(registry.register(Robot(robot_id="desk-1", base_url="http://desk-1.local")))
        manager = hub.app.state.robot_voice_manager
        assert hub.get("/privacy/state", headers=BEARER).json() == {"privacy_mode": True, "robots": 1}  # registered but not armed: privacy mode on
        manager.arm_for = lambda robot_id: object()  # "Hey Reachy" armed: privacy mode off
        assert hub.get("/privacy/state", headers=BEARER).json() == {"privacy_mode": False, "robots": 1}
        login(hub)
        assert hub.get("/privacy/state").json()["privacy_mode"] is False  # the owner's own session may read it too


def test_companion_cores_own_hub_client_reads_the_real_route_and_a_wrong_token_is_an_error_it_treats_as_unknown(monkeypatch):
    from companion_core.hub_client import HubClient

    hub, _core, _store, _memory, registry = build(monkeypatch)
    with hub:
        async def ask(token):
            client = HubClient("http://hub", transport=httpx.ASGITransport(app=hub.app), bearer_token=token)
            try:
                return await client.get_privacy_state()
            finally:
                await client._client.aclose()

        assert asyncio.run(ask("test-token")) == {"privacy_mode": True, "robots": 0}
        asyncio.run(registry.register(Robot(robot_id="desk-1", base_url="http://desk-1.local")))
        hub.app.state.robot_voice_manager.arm_for = lambda robot_id: object()
        assert asyncio.run(ask("test-token"))["privacy_mode"] is False
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(ask("wrong"))  # capture treats any error as unknown and does not propose anything
