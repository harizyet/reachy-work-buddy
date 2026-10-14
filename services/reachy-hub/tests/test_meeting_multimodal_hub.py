"""Phase 53: the hub's owner-only proxy for multimodal meeting intelligence over a real in-process core (flag and library on, page text from a fake reader under the real access rules)."""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "companion-core" / "tests"))

from companion_core.app import create_app as create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meeting_multimodal.store import InMemoryMultimodalStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient
from mm_fixtures import ARCH, COST, DECK_A, FakeLibrary, FakeStores, Model, World
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

from shared.models.response import Privacy

CSRF = {"X-Reachy-CSRF": "1"}
CHOICES = [("jetson edge node", None, "Edge Architecture"), ("budget forecast", None, "Cost Model")]


class Recording(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self.inner, self.seen = httpx.ASGITransport(app=app), []

    async def handle_async_request(self, request):
        self.seen.append((request.method, request.url.path, dict(request.headers)))
        return await self.inner.handle_async_request(request)


def make(monkeypatch, *, enabled=True, sensitive_meeting=False):
    for name, on in (("MEETING_MULTIMODAL_ENABLED", enabled), ("DOCUMENT_LIBRARY_ENABLED", True)):
        monkeypatch.setenv(name, "true") if on else monkeypatch.delenv(name, raising=False)
    world = World([ARCH, COST], model=Model(CHOICES), sensitivity=Privacy.SENSITIVE if sensitive_meeting else Privacy.WORK_PRIVATE)
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=world.tasks, planner_store=world.planner, meeting_store=world.meetings, run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, llm_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        document_store=FakeLibrary().store, document_sources=FakeStores(), run_document_sync=False,
        meeting_multimodal_store=InMemoryMultimodalStore() if enabled else None, meeting_multimodal_provider=world.model.provider, run_multimodal_runner=False,
    )
    transport = Recording(core)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    embodiment = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    client = TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token", accounts_service_token="svc",
        companion_core_client=CompanionCoreClient("http://core", transport=transport),
        client_factory=lambda url: EmbodimentClient(url, transport=httpx.ASGITransport(app=embodiment)),
    ))
    client.seen, client.core, client.world = transport.seen, core, world
    return client


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200
    return client


def prepare(client):
    """Put the meeting and a document into the core's stores and give core's service the fake page reader."""
    world = client.world
    service = client.core.state.meeting_multimodal_service
    service.documents = world.lib
    world.lib.deletion_listeners.append(service.document_deleted)

    async def go():
        world.meetings._meetings[world.meeting.id] = world.meeting
        return await world.lib.add(*DECK_A)

    client.doc = asyncio.run(go())
    client.mid = world.meeting.id
    return client


def test_only_the_owner_session_with_csrf_reaches_it(monkeypatch):
    with make(monkeypatch) as client:
        prepare(client)
        m = client.mid
        for method, path in (("get", "/meeting-multimodal/config"), ("get", f"/meetings/{m}/multimodal")):
            assert getattr(client, method)(path).status_code == 401
            assert getattr(client, method)(path, headers={"Authorization": "Bearer test-token"}).status_code == 401  # the robot-control bearer is not accepted
        login(client)
        assert client.post(f"/meetings/{m}/multimodal/attachments", json={"document_id": client.doc.id}).status_code == 403  # no CSRF header
        assert client.post(f"/meetings/{m}/multimodal/ask", json={"question": "what?!"}).status_code == 403
        assert client.put(f"/meetings/{m}/multimodal/windows/0-2/review", json={"decision": "no_slide"}).status_code == 403
        assert client.delete(f"/meetings/{m}/multimodal/attachments/{client.doc.id}").status_code == 403
        assert client.post("/meeting-multimodal/items/x/accept", json={}).status_code == 403
        assert client.get("/meeting-multimodal/config").json() == {"enabled": True}


def test_the_owner_flow_through_the_hub_and_the_trusted_ceiling(monkeypatch):
    with make(monkeypatch, sensitive_meeting=True) as client:
        prepare(client)
        login(client)
        m = client.mid
        assert client.get(f"/meetings/{m}/multimodal").status_code == 200  # a sensitive meeting is reachable because the hub, not the request, sets the ceiling
        assert all(headers.get("x-reachy-access-ceiling") == "sensitive" for _, path, headers in client.seen if "multimodal" in path)
        spoofed = client.get(f"/meetings/{m}/multimodal", headers={"X-Reachy-Access-Ceiling": "public"})
        assert spoofed.status_code == 200  # a header from the browser is overwritten by the hub's own
        assert client.post(f"/meetings/{m}/multimodal/attachments", json={"document_id": client.doc.id}, headers=CSRF).json()["created"]
        assert client.post(f"/meetings/{m}/multimodal/alignment", json={}, headers=CSRF).json()["alignment"]["state"] == "queued"
        assert asyncio.run(_work(client))
        view = client.get(f"/meetings/{m}/multimodal").json()
        assert [w["shown"]["page"] for w in view["windows"]] == [2, 4]
        key = view["windows"][0]["window_key"]
        reviewed = client.put(f"/meetings/{m}/multimodal/windows/{key}/review", json={"decision": "confirmed"}, headers=CSRF).json()
        assert reviewed["window"]["review_status"] == "confirmed"
        assert client.delete(f"/meetings/{m}/multimodal/windows/{key}/review", headers=CSRF).json() == {"cleared": True}
        assert client.delete(f"/meetings/{m}/multimodal/attachments/{client.doc.id}", headers=CSRF).json() == {"unlinked": True}


async def _work(client):
    return await client.core.state.meeting_multimodal_service.process_next()


def test_bad_input_is_refused_at_the_hub_and_core_refusals_are_fixed_messages(monkeypatch):
    with make(monkeypatch) as client:
        prepare(client)
        login(client)
        m = client.mid
        assert client.post(f"/meetings/{m}/multimodal/attachments", json={"document_id": "../x"}, headers=CSRF).status_code == 422
        assert client.post(f"/meetings/{m}/multimodal/attachments", json={"document_id": client.doc.id, "extra": 1}, headers=CSRF).status_code == 422
        assert client.put(f"/meetings/{m}/multimodal/windows/abc/review", json={"decision": "no_slide"}, headers=CSRF).status_code == 422
        assert client.put(f"/meetings/{m}/multimodal/windows/0-2/review", json={"decision": "maybe"}, headers=CSRF).status_code == 422
        assert client.post(f"/meetings/{m}/multimodal/ask", json={"question": "x"}, headers=CSRF).status_code == 422
        assert client.post("/meetings/nope/multimodal/attachments", json={"document_id": client.doc.id}, headers=CSRF).json()["detail"] == "No such meeting"
        assert client.post(f"/meetings/{m}/multimodal/alignment", json={}, headers=CSRF).json()["detail"] == "Attach a processed document first"


def test_with_core_having_the_feature_off_the_hub_says_so(monkeypatch):
    with make(monkeypatch, enabled=False) as client:
        login(client)
        assert client.get("/meeting-multimodal/config").json() == {"enabled": False}
        assert client.get("/meetings/x/multimodal").status_code == 404
