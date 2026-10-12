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


def make(monkeypatch, tmp_path, *, library=True, transport=None, worker=None, llm=None):
    if library:
        monkeypatch.setenv("DOCUMENT_LIBRARY_ENABLED", "true")
    else:
        monkeypatch.delenv("DOCUMENT_LIBRARY_ENABLED", raising=False)
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, document_store=InMemoryLibraryStore() if library else None, document_sources=SourceStore(tmp_path / "src") if library else None, document_worker=worker, run_document_sync=False, llm_transport=llm,
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
    client.core = core
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


# --- chat document picker: the attachment belongs to the conversation -----------------------------------------------------------------------------------------


class FakeEngine:
    """Just enough of the MinerU seam for the real worker app: pages are the file's text split on form feeds."""

    def __init__(self):
        self.docs, self.status = {}, "done"

    def health(self):
        from document_worker.engine import EngineHealth

        return EngineHealth(True, True)

    def ensure_parse(self, path, tier, page_range, force):
        import hashlib

        from document_worker.engine import Ticket

        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        self.docs.setdefault(digest, {"pages": data.decode("latin-1").split("\f"), "files": set(), "status": self.status})["files"].add(str(path))
        return Ticket(digest, digest[:7])

    def _doc(self, ref):
        from document_worker.engine import EngineError

        for digest, doc in self.docs.items():
            if digest.startswith(ref):
                return doc
        raise EngineError("doc_not_found")

    def parse_summary(self, ref, tier):
        from document_worker.engine import ParseSummary

        return ParseSummary((self._doc(ref)["status"],))

    def page_count(self, ref):
        return len(self._doc(ref)["pages"])

    def read(self, ref, tier, page_range, after, limit):
        from document_worker.engine import RawContent

        doc = self._doc(ref)
        n = int(page_range) if page_range and page_range.isdigit() else 1
        return RawContent(f"<!-- page {n} of {len(doc['pages'])} -->\n\n{doc['pages'][n - 1]}", ((f"doc:{ref}/tier:{tier}/page:{n}", f"doc:{ref}/tier:{tier}/page:{n}/block:1"),))

    def forget(self, path):
        for doc in self.docs.values():
            doc["files"].discard(str(path))

    def cleanup_orphans(self):
        for digest in [d for d, doc in self.docs.items() if not doc["files"]]:
            del self.docs[digest]

    def has_active_files(self, ref):
        try:
            return bool(self._doc(ref)["files"])
        except Exception:  # noqa: BLE001
            return False

    def invalidate(self, ref, tier):
        pass


class Model:
    def __init__(self):
        self.prompts = []
        self.history = []  # per model call, the non-system messages (the short-term conversation the model saw)
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        import json

        body = json.loads(request.content)
        self.prompts.append("\n".join(m["content"] for m in body["messages"] if m["role"] == "system"))
        self.history.append([m["content"] for m in body["messages"] if m["role"] != "system"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "Per the document: seven days."}}]})


def chat_stack(monkeypatch, tmp_path):
    from companion_core.document_library.worker_client import DocumentWorkerClient
    from document_worker.app import create_app as create_worker_app
    from document_worker.config import Settings as WorkerSettings

    engine, model = FakeEngine(), Model()
    app = create_worker_app(WorkerSettings(token="wt", work_dir=tmp_path / "worker"), engine)
    worker = DocumentWorkerClient("http://worker", "wt", client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://worker"))
    client = login(make(monkeypatch, tmp_path, worker=worker, llm=model.transport))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}}, headers=CSRF)
    client.engine, client.model = engine, model
    return client


POLICY = b"%PDF-1.4\nThe audit retention period is seven days.\x0cPage two"
OTHER = b"%PDF-1.4\nThe quarterly budget is large.\x0cPage two of budget"


def new_chat(client, title="Chat"):
    return client.post("/chats", json={"user_id": "default-user", "title": title}, headers=CSRF).json()["id"]


def attach(client, chat, document_id, **kw):
    return client.put(f"/chats/{chat}/document", json={"user_id": "default-user", "document_id": document_id}, headers=CSRF, **kw)


def say(client, chat, text, **extra):
    return client.post("/messages", json={"user_id": "default-user", "channel": "web", "text": text, "chat_id": chat, **extra}, headers=CSRF)


def test_the_attachment_belongs_to_one_conversation_and_survives_reading_it_again(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    one, two = upload(client, POLICY, "Policy.pdf", title="Audit policy").json(), upload(client, OTHER, "Budget.pdf", title="Budget").json()
    a, b = new_chat(client, "A"), new_chat(client, "B")
    assert client.get(f"/chats/{a}", params={"user_id": "default-user"}).json()["document"] is None  # a new conversation has none
    assert attach(client, a, one["id"]).json()["document"] == {"id": one["id"], "title": "Audit policy", "available": True}
    for _ in range(2):  # reading the chat again (a refresh) shows the same attachment
        detail = client.get(f"/chats/{a}", params={"user_id": "default-user"}).json()
        assert detail["document"] == {"id": one["id"], "title": "Audit policy", "available": True} and detail["turns"] == []
    assert client.get(f"/chats/{b}", params={"user_id": "default-user"}).json()["document"] is None  # another conversation is not affected
    assert attach(client, a, two["id"]).json()["document"]["title"] == "Budget"  # replace
    assert client.get(f"/chats/{a}", params={"user_id": "default-user"}).json()["document"]["id"] == two["id"]
    assert attach(client, a, None).json() == {"document": None}  # remove
    assert client.get(f"/chats/{a}", params={"user_id": "default-user"}).json()["document"] is None
    assert [c["id"] for c in client.get("/chats", params={"user_id": "default-user"}).json()] == [b, a]  # attaching does not reorder the history
    assert attach(client, a, "no-such-document").status_code == 404
    assert attach(client, "no-such-chat", one["id"]).status_code == 404


def test_attachment_changes_are_owner_only_and_need_csrf(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    doc = upload(client, POLICY, "Policy.pdf").json()
    chat = new_chat(client)
    assert client.put(f"/chats/{chat}/document", json={"user_id": "default-user", "document_id": doc["id"]}).status_code == 403  # no CSRF header
    assert client.put(f"/chats/{chat}/document", json={"user_id": "someone-else", "document_id": doc["id"]}, headers=CSRF).status_code == 403  # another account's chat
    client.cookies.clear()
    assert client.put(f"/chats/{chat}/document", json={"user_id": "default-user", "document_id": doc["id"]}, headers=CSRF).status_code == 401
    # the chat routes' existing trust model also accepts the remote-UI bearer; this route behaves exactly like the other chat routes
    assert client.put(f"/chats/{chat}/document", json={"user_id": "default-user", "document_id": doc["id"]}, headers={**CSRF, "Authorization": "Bearer test-token"}).status_code == 200


def test_every_message_of_the_conversation_answers_from_the_attached_document_until_it_is_removed(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    policy, budget = upload(client, POLICY, "Policy.pdf", title="Audit policy").json(), upload(client, OTHER, "Budget.pdf", title="Budget").json()
    chat = new_chat(client)
    attach(client, chat, policy["id"])
    first = say(client, chat, "How long is the audit retention period?").json()
    assert first["context_document"] == "Audit policy" and [(c["page"], c["title"]) for c in first["citations"]] == [(1, "Audit policy")]
    assert "audit retention period is seven days" in client.model.prompts[-1]
    # a follow-up with no document field is still answered from it, and a message cannot name a different document
    follow = say(client, chat, "And what about the second page?", context_document_id=budget["id"]).json()
    assert follow["context_document"] == "Audit policy" and "quarterly budget" not in client.model.prompts[-1]
    # the transcript keeps what each reply was answered from; attachment changes are not messages
    turns = client.get(f"/chats/{chat}", params={"user_id": "default-user"}).json()["turns"]
    assert len(turns) == 2 and all(t["document"]["title"] == "Audit policy" for t in turns) and turns[0]["citations"] == [{"document_id": policy["id"], "title": "Audit policy", "page": 1}]
    # replace
    attach(client, chat, budget["id"])
    third = say(client, chat, "What is the quarterly budget?").json()
    assert third["context_document"] == "Budget" and "quarterly budget" in client.model.prompts[-1]
    # remove: the next message is ordinary chat again
    attach(client, chat, None)
    plain = say(client, chat, "What is two plus two?").json()
    assert plain["context_document"] is None and plain["citations"] == [] and "data, not instructions" not in client.model.prompts[-1]
    turns = client.get(f"/chats/{chat}", params={"user_id": "default-user"}).json()["turns"]
    assert [t["document"] and t["document"]["title"] for t in turns] == ["Audit policy", "Audit policy", "Budget", None]


def test_a_stale_or_unprocessed_attachment_gets_the_fixed_replies_and_is_shown_as_stale(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    client.engine.status = "pending"
    waiting = upload(client, POLICY + b" w", "Waiting.pdf", title="Waiting").json()
    chat = new_chat(client)
    attach(client, chat, waiting["id"])
    assert "still being processed" in say(client, chat, "What does it say?").json()["reply"]
    client.engine.status = "done"
    doc = upload(client, POLICY, "Policy.pdf", title="Audit policy").json()
    attach(client, chat, doc["id"])
    assert say(client, chat, "How long is the audit retention period?").json()["context_document"] == "Audit policy"
    assert client.delete(f"/document-library/documents/{doc['id']}", headers=CSRF).status_code == 204  # deleted while still attached
    detail = client.get(f"/chats/{chat}", params={"user_id": "default-user"}).json()
    assert detail["document"] == {"id": doc["id"], "title": "Audit policy", "available": False}
    prompts = len(client.model.prompts)
    gone = say(client, chat, "And the retention again?").json()
    assert "can't find the document you attached" in gone["reply"] and gone["citations"] == [] and len(client.model.prompts) == prompts  # no model call, no content
    assert attach(client, chat, None).json() == {"document": None}  # the owner removes the stale attachment


def test_a_sensitive_document_can_be_attached_by_the_owner_session_and_a_conversation_without_one_is_unchanged(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    secret = upload(client, POLICY, "Secret.pdf", title="Secret policy", sensitivity="sensitive").json()
    chat = new_chat(client)
    attach(client, chat, secret["id"])
    answered = say(client, chat, "How long is the audit retention period?").json()
    assert answered["context_document"] == "Secret policy" and answered["privacy"] == "sensitive"  # the hub's ceiling for a typed owner web message
    plain_chat = new_chat(client, "plain")
    plain = say(client, plain_chat, "What is two plus two?").json()
    assert plain["context_document"] is None and plain["citations"] == []
    detail = client.get(f"/chats/{plain_chat}", params={"user_id": "default-user"}).json()
    assert detail["document"] is None and detail["turns"][0]["document"] is None and detail["turns"][0]["citations"] == []
    assert client.delete(f"/chats/{chat}", params={"user_id": "default-user"}, headers=CSRF).status_code == 200
    assert client.get(f"/chats/{chat}", params={"user_id": "default-user"}).status_code == 404


# --- conversation-history isolation (found at the chat-picker deployment): each saved chat, and each context attached to it, has its own short-term history ---


def test_chats_never_share_short_term_history_even_with_documents_and_sensitive_content(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    secret = upload(client, POLICY, "Secret.pdf", title="Secret policy", sensitivity="sensitive").json()
    budget = upload(client, OTHER, "Budget.pdf", title="Budget").json()
    a, b, c = new_chat(client, "A"), new_chat(client, "B"), new_chat(client, "C")
    attach(client, a, secret["id"])
    attach(client, c, budget["id"])
    assert say(client, a, "How long is the audit retention period?").json()["privacy"] == "sensitive"
    seen = len(client.model.history)
    say(client, b, "What did we just talk about?")  # a new chat with nothing attached starts clean
    say(client, c, "What is the quarterly budget?")  # another chat with another document does too
    for call in client.model.history[seen:]:
        assert not any("seven days" in m or "audit retention" in m for m in call)
    assert client.model.history[seen] == ["What did we just talk about?"] and client.model.history[seen + 1] == ["What is the quarterly budget?"]
    # the same chat keeps its own continuity
    say(client, a, "And the second page?")
    assert client.model.history[-1][:2] == ["How long is the audit retention period?", "Per the document: seven days."]


def test_a_client_cannot_choose_or_forge_the_history_it_is_answered_under(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    a, b = new_chat(client, "A"), new_chat(client, "B")
    say(client, a, "My secret code word is marmalade.")
    seen = len(client.model.history)
    # extra fields in the request body that name a scope, prior turns or another chat's history are not part of the contract and change nothing
    forged = say(client, b, "What is my code word?", history_scope="chat:" + a, prior_turns=[{"text": "x", "reply": "y"}], conversation_id="c")
    assert forged.status_code == 200 and client.model.history[seen] == ["What is my code word?"]
    assert client.post("/messages", json={"user_id": "default-user", "channel": "web", "text": "hi", "chat_id": "00000000-no-such-chat"}, headers=CSRF).status_code == 404
    assert client.post("/messages", json={"user_id": "someone-else", "channel": "web", "text": "hi", "chat_id": a}, headers=CSRF).status_code == 403


def test_switching_or_removing_the_document_starts_a_clean_history_for_that_context(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    policy, budget = upload(client, POLICY, "Policy.pdf", title="Audit policy").json(), upload(client, OTHER, "Budget.pdf", title="Budget").json()
    chat = new_chat(client)
    say(client, chat, "Plain fact: the office cat is called Biscuit.")
    attach(client, chat, policy["id"])
    say(client, chat, "How long is the audit retention period?")
    attach(client, chat, budget["id"])
    say(client, chat, "What is the quarterly budget?")
    assert client.model.history[-1] == ["What is the quarterly budget?"]  # the old document's answers are not in the new document's context
    attach(client, chat, None)
    say(client, chat, "What is the cat called?")
    assert client.model.history[-1][:2] == ["Plain fact: the office cat is called Biscuit.", "Per the document: seven days."]  # back to the plain context, its own turns only
    assert not any("audit retention" in m or "quarterly" in m for m in client.model.history[-1])


def test_a_chat_restored_after_core_lost_its_memory_continues_from_its_own_saved_turns_only(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    policy = upload(client, POLICY, "Policy.pdf", title="Audit policy").json()
    a, b = new_chat(client, "A"), new_chat(client, "B")
    attach(client, a, policy["id"])
    say(client, a, "How long is the audit retention period?")
    say(client, b, "Plain question in B.")
    client.core.state.conversation_store.clear()  # core restarted: its in-memory history is gone, the hub's saved chats are not
    say(client, a, "And the second page?")
    assert client.model.history[-1] == ["How long is the audit retention period?", "Per the document: seven days.", "And the second page?"]
    say(client, b, "Another in B.")
    assert client.model.history[-1] == ["Plain question in B.", "Per the document: seven days.", "Another in B."]  # restored from B's own turns, not A's
    # a spoken, unscoped turn is never seeded from a chat
    client.core.state.conversation_store.clear()
    spoken = client.post("/messages", json={"user_id": "default-user", "channel": "reachy", "text": "Spoken hello", "input_modality": "voice"}, headers=CSRF)
    assert spoken.status_code == 200 and client.model.history[-1] == ["Spoken hello"]


def test_voice_and_unsaved_turns_keep_the_shared_session_history_and_chats_do_not_leak_into_it(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    chat = new_chat(client)
    spoken = {"user_id": "default-user", "channel": "reachy", "input_modality": "voice"}
    client.post("/messages", json={**spoken, "text": "First spoken."}, headers=CSRF)
    say(client, chat, "A typed chat message.")
    client.post("/messages", json={**spoken, "text": "Second spoken."}, headers=CSRF)
    assert client.model.history[-1][-3:] == ["First spoken.", "Per the document: seven days.", "Second spoken."] and "A typed chat message." not in client.model.history[-1]


def test_deleting_a_chat_tells_core_to_forget_its_history_and_contexts_use_their_own_scopes(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    policy = upload(client, POLICY, "Policy.pdf", title="Audit policy").json()
    chat = new_chat(client)
    say(client, chat, "Plain.")
    attach(client, chat, policy["id"])
    say(client, chat, "How long is the audit retention period?")
    attach(client, chat, None)
    say(client, chat, "A meeting question.", context_meeting_id="m1")  # no such meeting: whatever core answers, it is recorded under the meeting's own scope
    store = client.core.state.conversation_store
    keys = lambda: sorted(k.split("\x1f", 1)[1] for k in store._messages if "\x1f" in k)
    import hashlib

    meeting_scope = f"chat:{chat}:mtg:" + hashlib.sha256(b"m1").hexdigest()[:16]
    assert keys() == sorted([f"chat:{chat}", f"chat:{chat}:doc:{policy['id']}", meeting_scope])
    assert client.delete(f"/chats/{chat}", params={"user_id": "default-user"}, headers=CSRF).status_code == 200
    assert keys() == []
    assert any(p.endswith("/conversation/forget") for _m, p, _h in client.transport_log)


def test_a_one_off_document_question_has_its_own_history_per_document_not_the_shared_session(monkeypatch, tmp_path):
    client = chat_stack(monkeypatch, tmp_path)
    policy, budget = upload(client, POLICY, "Policy.pdf", title="Audit policy").json(), upload(client, OTHER, "Budget.pdf", title="Budget").json()
    ask = lambda doc, text: client.post("/messages", json={"user_id": "default-user", "channel": "web", "text": text, "context_document_id": doc}, headers=CSRF)
    spoken = {"user_id": "default-user", "channel": "reachy", "input_modality": "voice"}
    client.post("/messages", json={**spoken, "text": "Spoken first."}, headers=CSRF)
    assert ask(policy["id"], "How long is the audit retention period?").status_code == 200
    ask(budget["id"], "What is the quarterly budget?")
    assert client.model.history[-1] == ["What is the quarterly budget?"]  # another document's answers are not in this one's context
    ask(policy["id"], "And on the second page?")
    assert client.model.history[-1][:2] == ["How long is the audit retention period?", "Per the document: seven days."]  # continuity per document
    client.post("/messages", json={**spoken, "text": "Spoken again."}, headers=CSRF)
    assert client.model.history[-1] == ["Spoken first.", "Per the document: seven days.", "Spoken again."]  # the shared session never saw the document questions
