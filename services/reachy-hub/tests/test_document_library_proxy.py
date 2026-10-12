"""Phase 50J: the hub's owner-only document library proxy over a real in-process core (library on, no worker: documents stay `uploaded`)."""

import asyncio

import httpx
from companion_core.app import create_app as create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.document_library.source_store import SourceStore
from companion_core.document_library.store import (
    InMemoryDocumentStore as InMemoryLibraryStore,
)
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

CSRF = {"X-Reachy-CSRF": "1"}
PDF = b"%PDF-1.4\nThe retention requirement is 7 days.\n"


class Recording(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self.inner, self.seen = httpx.ASGITransport(app=app), []

    async def handle_async_request(self, request):
        self.seen.append((request.method, request.url.path, dict(request.headers)))
        return await self.inner.handle_async_request(request)


def make(monkeypatch, tmp_path, *, library=True, transport=None):
    if library:
        monkeypatch.setenv("DOCUMENT_LIBRARY_ENABLED", "true")
    else:
        monkeypatch.delenv("DOCUMENT_LIBRARY_ENABLED", raising=False)
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, document_store=InMemoryLibraryStore() if library else None, document_sources=SourceStore(tmp_path / "src") if library else None, run_document_sync=False,
    )
    transport = transport or Recording(core)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    embodiment = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    client = TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False, session_secret_key="test-session-secret", remote_ui_token="test-token", accounts_service_token="svc",
        companion_core_client=CompanionCoreClient("http://core", transport=transport),
        client_factory=lambda url: EmbodimentClient(url, transport=httpx.ASGITransport(app=embodiment)),
    ))
    client.transport_log = getattr(transport, "seen", [])
    return client


def login(client):
    assert client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF).status_code == 200
    return client


def upload(client, data=PDF, name="Spec.pdf", **form):
    return client.post("/document-library/documents", files={"file": (name, data, "application/octet-stream")}, data=form, headers=CSRF)


def test_only_the_owner_session_with_csrf_reaches_the_library(monkeypatch, tmp_path):
    client = make(monkeypatch, tmp_path)
    for method, path in (("get", "/document-library/config"), ("get", "/document-library/documents"), ("get", "/document-library/documents/x/summaries")):
        assert getattr(client, method)(path).status_code == 401
        assert getattr(client, method)(path, headers={"Authorization": "Bearer test-token"}).status_code == 401  # the robot-control bearer is not accepted
    login(client)
    assert client.post("/document-library/documents", files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 403  # no CSRF header
    assert client.delete("/document-library/documents/x").status_code == 403
    assert client.get("/document-library/documents").json() == []


def test_upload_catalogue_edit_and_delete_through_the_hub(monkeypatch, tmp_path):
    client = login(make(monkeypatch, tmp_path))
    created = upload(client, sensitivity="sensitive", project_scope="Alpha", title="Tender")
    assert created.status_code == 201 and created.headers["cache-control"] == "no-store"
    doc = created.json()
    assert (doc["title"], doc["sensitivity"], doc["project_scope"], doc["state"]) == ("Tender", "sensitive", "Alpha", "uploaded")
    assert client.get("/document-library/config").json() == {"enabled": True}
    assert [d["id"] for d in client.get("/document-library/documents").json()] == [doc["id"]]
    assert client.patch(f"/document-library/documents/{doc['id']}", json={"title": "Renamed", "project_scope": None}, headers=CSRF).json()["title"] == "Renamed"
    assert client.patch(f"/document-library/documents/{doc['id']}", json={"state": "ready"}, headers=CSRF).status_code == 422
    assert upload(client, b"nonsense", "x.pdf").status_code == 415 and upload(client, PDF, "x.exe").status_code == 415
    assert client.get("/document-library/documents/not.an.id!").status_code in (404, 422)
    assert client.delete(f"/document-library/documents/{doc['id']}", headers=CSRF).status_code == 204
    assert client.get(f"/document-library/documents/{doc['id']}").status_code == 404


def test_the_hub_alone_sets_the_ceiling_and_a_browser_header_changes_nothing(monkeypatch, tmp_path):
    client = login(make(monkeypatch, tmp_path))
    doc = upload(client, sensitivity="sensitive").json()
    # sensitive is readable by the owner session: core gets past the class check (a 403 otherwise) and then says there is no worker here
    read = client.get(f"/document-library/documents/{doc['id']}/read", headers={"X-Reachy-Access-Ceiling": "public"})
    assert read.status_code == 503 and "not configured" in read.json()["detail"]
    sent = [h for m, p, h in client.transport_log if p.endswith("/read")]
    assert sent and all(h.get("x-reachy-access-ceiling") == "sensitive" for h in sent)  # what the browser sent was not forwarded
    assert client.post(f"/document-library/documents/{doc['id']}/search", json={"query": "x"}, headers=CSRF).status_code == 503
    assert client.post(f"/document-library/documents/{doc['id']}/summaries", json={"style": "executive"}, headers=CSRF).status_code == 503
    assert client.post(f"/document-library/documents/{doc['id']}/search", json={"query": ""}, headers=CSRF).status_code == 422
    assert client.post(f"/document-library/documents/{doc['id']}/summaries", json={"style": "poem"}, headers=CSRF).status_code == 422


def test_with_the_library_off_in_core_the_config_says_so_and_the_rest_404(monkeypatch, tmp_path):
    client = login(make(monkeypatch, tmp_path, library=False))
    assert client.get("/document-library/config").json() == {"enabled": False}
    assert client.get("/document-library/documents").status_code == 404
    assert upload(client).status_code == 404


def test_a_core_that_is_down_is_a_fixed_502_without_details(monkeypatch, tmp_path):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret internal address 10.0.0.9", request=request)

    client = login(make(monkeypatch, tmp_path, transport=httpx.MockTransport(down)))
    for response in (client.get("/document-library/documents"), client.get("/document-library/config")):
        assert response.status_code == 502 and "10.0.0.9" not in response.text and response.json()["detail"] == "The document library is unavailable"


def test_inspector_routes_need_the_owner_session_and_pass_files_with_safe_headers(monkeypatch, tmp_path):
    client = make(monkeypatch, tmp_path)
    paths = ("/document-library/documents/x/inspect/pages/1", "/document-library/documents/x/inspect/pages/1/image", "/document-library/documents/x/inspect/pages/1/blocks/2/image",
             "/document-library/documents/x/export", "/document-library/documents/x/original")
    for path in paths:
        assert client.get(path).status_code == 401 and client.get(path, headers={"Authorization": "Bearer test-token"}).status_code == 401, path
    login(client)
    doc = upload(client, sensitivity="sensitive", title="Tender").json()
    original = client.get(f"/document-library/documents/{doc['id']}/original")
    assert original.status_code == 200 and original.content == PDF and original.headers["content-type"] == "application/pdf"  # a sensitive original, readable by the owner session
    assert original.headers["content-disposition"] == 'attachment; filename="Spec.pdf"' and original.headers["content-security-policy"] == "sandbox"
    assert original.headers["x-content-type-options"] == "nosniff" and original.headers["cache-control"] == "no-store"
    # no worker in this chain: the page and export routes answer with core's fixed refusal, not an error
    for path in (f"/document-library/documents/{doc['id']}/inspect/pages/1", f"/document-library/documents/{doc['id']}/export", f"/document-library/documents/{doc['id']}/inspect/pages/1/image"):
        r = client.get(path)
        assert r.status_code == 503 and "not configured" in r.json()["detail"], path
    assert client.get(f"/document-library/documents/{doc['id']}/export", params={"format": "pdf"}).status_code == 422
    assert client.get(f"/document-library/documents/{doc['id']}/inspect/pages/0").status_code == 422
    assert client.get(f"/document-library/documents/{doc['id']}/inspect/pages/1/image", params={"format": "gif"}).status_code == 422
    sent = [h for m, p, h in client.transport_log if p.endswith("/original")]
    assert sent and all(h.get("x-reachy-access-ceiling") == "sensitive" for h in sent)
    assert client.get("/document-library/documents/nope/original").status_code == 404
