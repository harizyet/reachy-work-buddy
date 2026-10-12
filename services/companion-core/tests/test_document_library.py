"""Phase 50B (docs/phase-50.md): the document library. The source store, the service rules and the routes over the real app, and deletion through the REAL document worker app
(an in-process ASGI chain) with a fake backend engine, which reproduces the behaviours the 50A spike found in MinerU (identity by hash, forgetting leaves the row until orphan cleanup)."""

import asyncio
import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.document_library.models import DocumentState, Priority, tier_for
from companion_core.document_library.source_store import (
    SourceCorrupt,
    SourceRejected,
    SourceStore,
)
from companion_core.document_library.store import (
    InMemoryDocumentStore as InMemoryLibraryStore,
)
from companion_core.document_library.worker_client import DocumentWorkerClient
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from document_worker.app import create_app as create_worker_app
from document_worker.config import Settings as WorkerSettings
from document_worker.engine import (
    EngineError,
    EngineHealth,
    ParseSummary,
    RawContent,
    RawHit,
    Ticket,
)
from fastapi.testclient import TestClient

PDF = b"%PDF-1.4\nThe retention requirement is 7 days.\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
TOKEN = "worker-token"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def docx_bytes(valid: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("word/document.xml" if valid else "other.xml", "<w:document/>")
    return buffer.getvalue()


class FakeEngine:
    """The 50A behaviours that matter here: identity is the content hash, identical bytes share one backend document, search is global, forgetting a file leaves the document until orphans are
    cleaned. Pages are the original's text split on form feeds."""

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.fail = False
        self.parse_status = "done"
        self.invalidated: list[str] = []

    def health(self):
        return EngineHealth(True, True)

    def ensure_parse(self, path, tier, page_range, force):
        data = path.read_bytes()
        digest = sha(data)
        doc = self.docs.setdefault(digest, {"files": set(), "pages": data.decode("latin-1").split("\f"), "status": self.parse_status})
        doc["files"].add(str(path))
        return Ticket(digest, digest[:7])

    def _doc(self, ref):
        for digest, doc in self.docs.items():
            if digest.startswith(ref):
                return digest, doc
        raise EngineError("doc_not_found")

    def parse_summary(self, ref, tier):
        _, doc = self._doc(ref)
        return ParseSummary((doc["status"],), "parse_failed" if doc["status"] == "failed" else None)

    def page_count(self, ref):
        return len(self._doc(ref)[1]["pages"])

    def read(self, ref, tier, page_range, after, limit):
        _, doc = self._doc(ref)
        if doc["status"] != "done":
            raise EngineError("tier_not_cached")
        n = int(page_range) if page_range and page_range.isdigit() else 1
        return RawContent(f"<!-- page {n} of {len(doc['pages'])} -->\n\n{doc['pages'][n - 1]}", ((f"doc:{ref}/tier:{tier}/page:{n}", f"doc:{ref}/tier:{tier}/page:{n}/block:1"),))

    def read_locator(self, locator, context, limit):
        return RawContent(f"around {locator}", ((locator, locator),))

    def search(self, query, limit, offset):
        hits = []
        for digest, doc in self.docs.items():
            lines = [ln for page in doc["pages"] for ln in page.splitlines() if query.lower() in ln.lower()]
            if doc["files"] and lines:
                hits.append(RawHit(digest[:7], "\n\n".join(ln.replace(query, f"<mark>{query}</mark>") for ln in lines)))
        return hits[offset : offset + limit], len(hits)

    def invalidate(self, ref, tier):
        self.invalidated.append((ref, tier))
        self._doc(ref)[1]["status"] = self.parse_status

    def forget(self, path):
        if self.fail:
            raise EngineError("engine_unavailable")
        for doc in self.docs.values():
            doc["files"].discard(str(path))

    def cleanup_orphans(self):
        for digest in [d for d, doc in self.docs.items() if not doc["files"]]:
            del self.docs[digest]

    def has_active_files(self, ref):
        try:
            return bool(self._doc(ref)[1]["files"])
        except EngineError:
            return False


class Switch(httpx.AsyncBaseTransport):
    """The ASGI chain to the real worker app, with a switch to take the worker 'down' and a record of every call."""

    def __init__(self, app):
        self.inner, self.down, self.calls = httpx.ASGITransport(app=app), False, []

    async def handle_async_request(self, request):
        if self.down:
            raise httpx.ConnectError("worker down")
        self.calls.append((request.method, request.url.path))
        return await self.inner.handle_async_request(request)


class Env:
    def __init__(self, monkeypatch, tmp_path: Path, *, enabled=True, worker: DocumentWorkerClient | None = None, max_bytes: int | None = None):
        if enabled:
            monkeypatch.setenv("DOCUMENT_LIBRARY_ENABLED", "true")
        else:
            monkeypatch.delenv("DOCUMENT_LIBRARY_ENABLED", raising=False)
        if max_bytes:
            monkeypatch.setenv("DOCUMENT_LIBRARY_MAX_UPLOAD_BYTES", str(max_bytes))
        self.sources = SourceStore(tmp_path / "source")
        self.store = InMemoryLibraryStore()
        self.app = create_app(
            calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
            memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
            run_email_dispatch_task=False, llm_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
            document_store=self.store if enabled else None, document_sources=self.sources if enabled else None, document_worker=worker, run_document_sync=False,
        )

    def __enter__(self):
        self.client = TestClient(self.app).__enter__()
        return self

    def __exit__(self, *exc):
        return self.client.__exit__(*exc)

    @property
    def service(self):
        return self.app.state.document_library

    def run(self, coro):
        return self.client.portal.call(lambda: coro)

    def upload(self, data=PDF, name="Spec.pdf", **form):
        return self.client.post("/document-library/documents", files={"file": (name, data, "application/octet-stream")}, data=form)


@pytest.fixture
def env(monkeypatch, tmp_path):
    with Env(monkeypatch, tmp_path) as e:
        yield e


# --- the source store ---------------------------------------------------------------------------------------------


async def _chunks(data: bytes, size: int = 7):
    for i in range(0, len(data), size):
        yield data[i : i + size]


def _put(store: SourceStore, data: bytes, **kw):
    return asyncio.run(store.put(_chunks(data), max_bytes=kw.pop("max_bytes", 1000), head_ok=lambda head: head.startswith(b"%PDF-"), **kw))


def test_source_store_is_content_addressed_and_writes_once(tmp_path):
    store = SourceStore(tmp_path)
    digest, size, new = _put(store, PDF)
    assert (digest, size, new) == (sha(PDF), len(PDF), True)
    assert store.path_for(digest) == tmp_path / "sha256" / digest[:2] / digest[2:4] / digest
    assert _put(store, PDF) == (digest, len(PDF), False)  # the same bytes are not stored twice
    assert asyncio.run(store.verify(digest)) == len(PDF) and asyncio.run(store.read_verified(digest)) == PDF
    assert list((tmp_path / "tmp").iterdir()) == []  # nothing left behind


def test_source_store_reverifies_on_read_and_catches_tampering_and_loss(tmp_path):
    store = SourceStore(tmp_path)
    digest, *_ = _put(store, PDF)
    path = store.path_for(digest)
    path.chmod(0o640)
    path.write_bytes(PDF + b"tampered")
    for call in (store.verify, store.read_verified):
        with pytest.raises(SourceCorrupt):
            asyncio.run(call(digest))
    path.unlink()
    with pytest.raises(SourceCorrupt):
        asyncio.run(store.verify(digest))


def test_source_store_rejects_oversize_wrong_type_and_empty_without_committing(tmp_path):
    store = SourceStore(tmp_path)
    for data, status in ((PDF * 100, 413), (b"not a pdf at all", 415), (b"", 415)):
        with pytest.raises(SourceRejected) as exc:
            _put(store, data, max_bytes=100)
        assert exc.value.status == status
    assert not (tmp_path / "sha256").exists() and list((tmp_path / "tmp").iterdir()) == []


def test_source_store_only_accepts_a_real_sha256_name(tmp_path):
    for bad in ("../../etc/passwd", "abc", "G" * 64, ("a" * 63 + "/")):
        with pytest.raises(ValueError):
            SourceStore(tmp_path).path_for(bad)


# --- the routes over the real app ---------------------------------------------------------------------------------


def test_with_the_flag_off_nothing_exists(monkeypatch, tmp_path):
    with Env(monkeypatch, tmp_path, enabled=False) as env:
        assert env.app.state.document_library is None
        assert env.client.get("/document-library/config").status_code == 404
        assert env.client.get("/document-library/documents").status_code == 404
        assert env.upload().status_code == 404
        assert not (tmp_path / "source" / "sha256").exists()
        assert env.client.get("/documents").status_code == 200  # the older text-RAG route is untouched


def test_upload_stores_the_original_by_hash_and_defaults_to_the_conservative_class(env):
    r = env.upload()
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] == "uploaded" and body["sensitivity"] == "work-private" and body["project_scope"] is None
    assert body["title"] == "Spec" and body["filename"] == "Spec.pdf" and body["mime_type"] == "application/pdf"
    assert body["source_hash"] == sha(PDF) and body["size_bytes"] == len(PDF) and body["processing_priority"] == "background"
    assert env.sources.exists(sha(PDF))
    assert str(env.sources.root) not in r.text and "backend" not in r.text
    assert env.client.get("/document-library/config").json() == {"enabled": True}
    assert [d["id"] for d in env.client.get("/document-library/documents").json()] == [body["id"]]
    assert env.client.get(f"/document-library/documents/{body['id']}").json() == body


def test_upload_takes_the_owners_classification_project_and_priority(env):
    r = env.upload(sensitivity="sensitive", project_scope="  Project   StarWars ", title="  The  Tender ", processing_priority="normal")
    assert r.status_code == 201
    body = r.json()
    assert (body["sensitivity"], body["project_scope"], body["title"], body["processing_priority"]) == ("sensitive", "Project StarWars", "The Tender", "normal")
    assert env.upload(sensitivity="top-secret").status_code == 422
    assert env.upload(project_scope="x" * 101).status_code == 422


def test_upload_rejects_by_content_not_by_name(env):
    assert env.upload(b"plain text pretending", "notes.pdf").status_code == 415  # right extension, wrong bytes
    assert env.upload(PNG, "photo.pdf").status_code == 415  # a PNG named .pdf
    assert env.upload(PDF, "script.exe").status_code == 415
    assert env.upload(docx_bytes(False), "x.docx").status_code == 415  # a zip that is not a word package
    assert env.upload(b"", "empty.pdf").status_code == 415
    assert env.upload(PNG, "photo.PNG").status_code == 201 and env.upload(docx_bytes(), "memo.docx").status_code == 201
    assert env.upload(b"\xff\xd8\xff\xe0" + b"\x00" * 20, "pic.jpeg").json()["mime_type"] == "image/jpeg"
    assert len(env.client.get("/document-library/documents").json()) == 3  # the rejected ones left no record


def test_upload_enforces_the_byte_limit(monkeypatch, tmp_path):
    with Env(monkeypatch, tmp_path, max_bytes=60) as env:
        assert env.upload(PDF).status_code == 201
        r = env.upload(PDF + b"x" * 100)
        assert r.status_code == 413 and "x" * 5 not in r.text
        assert len(env.client.get("/document-library/documents").json()) == 1


def test_identical_bytes_are_two_documents_with_separate_policy_and_one_blob(env):
    a = env.upload(sensitivity="sensitive").json()
    b = env.upload(sensitivity="public").json()
    assert a["id"] != b["id"] and a["source_hash"] == b["source_hash"]
    assert (a["sensitivity"], b["sensitivity"]) == ("sensitive", "public")
    assert sum(1 for _ in (env.sources.root / "sha256").rglob(a["source_hash"])) == 1
    assert env.client.delete(f"/document-library/documents/{a['id']}").status_code == 204
    assert env.sources.exists(a["source_hash"])  # the other document still needs it
    assert env.client.get(f"/document-library/documents/{b['id']}").json()["sensitivity"] == "public"
    assert env.client.delete(f"/document-library/documents/{b['id']}").status_code == 204
    assert not env.sources.exists(a["source_hash"]) and env.client.get("/document-library/documents").json() == []


def test_metadata_changes_only_what_is_named_and_never_clears_policy(env):
    doc = env.upload(project_scope="Alpha").json()
    url = f"/document-library/documents/{doc['id']}"
    r = env.client.patch(url, json={"title": "Renamed", "sensitivity": "public"})
    assert r.json()["title"] == "Renamed" and r.json()["sensitivity"] == "public" and r.json()["project_scope"] == "Alpha"
    assert env.client.patch(url, json={"project_scope": None}).json()["project_scope"] is None  # an explicit null clears the project
    assert env.client.patch(url, json={"sensitivity": None}).status_code == 422
    assert env.client.patch(url, json={"processing_priority": None}).status_code == 422
    assert env.client.patch(url, json={"state": "ready"}).status_code == 422  # state is not editable from outside
    assert env.client.patch(url, json={"source_hash": "0" * 64}).status_code == 422
    assert env.client.patch(url, json={}).json()["title"] == "Renamed"
    assert env.client.patch(url, json={"processing_priority": "interactive"}).json()["processing_priority"] == "interactive"
    assert env.client.patch("/document-library/documents/nope", json={"title": "x"}).status_code == 404


def test_content_access_fails_closed_on_a_tampered_original_and_on_a_document_being_deleted(env):
    doc = env.upload().json()
    assert env.run(env.service.require_usable(doc["id"])).id == doc["id"]
    path = env.sources.path_for(doc["source_hash"])
    path.chmod(0o640)
    path.write_bytes(PDF + b"tampered")
    with pytest.raises(Exception) as exc:
        env.run(env.service.require_usable(doc["id"]))
    assert getattr(exc.value, "status", None) == 409
    env.run(env.store.begin_delete(doc["id"], env.service.clock()))
    with pytest.raises(Exception) as exc:
        env.run(env.service.require_usable(doc["id"]))
    assert getattr(exc.value, "status", None) == 404


def test_unknown_document_is_404_everywhere(env):
    assert env.client.get("/document-library/documents/nope").status_code == 404
    assert env.client.delete("/document-library/documents/nope").status_code == 404


# --- deletion through the real worker -----------------------------------------------------------------------------


@pytest.fixture
def backend(monkeypatch, tmp_path):
    engine = FakeEngine()
    switch = Switch(create_worker_app(WorkerSettings(token=TOKEN, work_dir=tmp_path / "worker"), engine))
    client = DocumentWorkerClient("http://worker", TOKEN, client=httpx.AsyncClient(transport=switch, base_url="http://worker"))
    with Env(monkeypatch, tmp_path, worker=client) as env:
        env.engine, env.worker, env.switch = engine, client, switch
        yield env


def _ingest(env, doc: dict, data: bytes = PDF) -> None:
    """Stand in for 50C: give the worker the original and record the backend reference on the document."""
    from shared.models.document_worker import WorkerTier

    status = env.run(env.worker.ingest(doc["id"], doc["source_hash"], WorkerTier.FLASH, "pdf", data))
    env.run(env.store.update(doc["id"], env.service.clock(), backend_ref=status.backend_ref, state=DocumentState.READY, tier="flash"))


def test_deleting_removes_the_backend_object_the_record_and_the_original(backend):
    doc = backend.upload().json()
    _ingest(backend, doc)
    assert backend.engine.docs
    assert backend.client.delete(f"/document-library/documents/{doc['id']}").status_code == 204
    assert backend.engine.docs == {} and not backend.sources.exists(doc["source_hash"])
    assert backend.client.get(f"/document-library/documents/{doc['id']}").status_code == 404


def test_deleting_one_of_two_identical_documents_keeps_the_other_readable_in_the_backend(backend):
    first, second = backend.upload().json(), backend.upload().json()
    _ingest(backend, first)
    _ingest(backend, second)
    assert backend.client.delete(f"/document-library/documents/{first['id']}").status_code == 204
    assert backend.engine.docs  # the other document still holds the shared backend object
    assert backend.sources.exists(second["source_hash"])
    assert backend.run(backend.worker.status(second["id"])).state.value == "ready"
    assert backend.client.delete(f"/document-library/documents/{second['id']}").status_code == 204
    assert backend.engine.docs == {} and not backend.sources.exists(second["source_hash"])


def test_a_deletion_the_worker_cannot_confirm_leaves_the_document_unusable_and_is_retried(backend):
    doc = backend.upload().json()
    _ingest(backend, doc)
    backend.engine.fail = True
    r = backend.client.delete(f"/document-library/documents/{doc['id']}")
    assert r.status_code == 502 and "retried" in r.json()["detail"]
    held = backend.client.get(f"/document-library/documents/{doc['id']}").json()
    assert held["state"] == "deleting" and backend.sources.exists(doc["source_hash"])
    assert backend.client.patch(f"/document-library/documents/{doc['id']}", json={"title": "back"}).status_code == 404  # it cannot be revived
    with pytest.raises(Exception) as exc:
        backend.run(backend.service.require_usable(doc["id"]))
    assert getattr(exc.value, "status", None) == 404
    assert backend.run(backend.service.finish_deletions()) == 0  # still failing
    backend.engine.fail = False
    assert backend.run(backend.service.finish_deletions()) == 1
    assert backend.client.get(f"/document-library/documents/{doc['id']}").status_code == 404
    assert backend.engine.docs == {} and not backend.sources.exists(doc["source_hash"])


def test_a_document_never_given_to_the_backend_deletes_without_a_worker(monkeypatch, tmp_path):
    with Env(monkeypatch, tmp_path, worker=None) as env:
        doc = env.upload().json()
        assert env.client.delete(f"/document-library/documents/{doc['id']}").status_code == 204
        assert not env.sources.exists(doc["source_hash"])
        held = env.upload().json()
        env.run(env.store.update(held["id"], env.service.clock(), backend_ref="abc1234"))
        assert env.client.delete(f"/document-library/documents/{held['id']}").status_code == 502  # a backend reference but no worker: not confirmed, kept for retry
        assert env.client.get(f"/document-library/documents/{held['id']}").json()["state"] == "deleting"


def test_worker_client_reduces_failures_to_a_status_and_a_code(tmp_path):
    from companion_core.document_library.worker_client import WorkerError

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized", "detail": "/data/work/secret.pdf"})

    client = DocumentWorkerClient("http://worker", "x", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse), base_url="http://worker"))
    with pytest.raises(WorkerError) as exc:
        asyncio.run(client.status("doc1"))
    assert (exc.value.status, exc.value.code) == (401, "unauthorized") and "secret" not in str(exc.value)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused: /data/work/secret.pdf")

    client = DocumentWorkerClient("http://worker", "x", client=httpx.AsyncClient(transport=httpx.MockTransport(down), base_url="http://worker"))
    with pytest.raises(WorkerError) as exc:
        asyncio.run(client.delete("doc1"))
    assert (exc.value.status, exc.value.code) == (0, "worker_unreachable") and "secret" not in str(exc.value)


# --- 50C: the lifecycle between the library and the worker --------------------------------------------------------

PAGES = b"%PDF-1.4\nPage one\nThe retention requirement is 7 days.\x0cPage two\nThe audit period is 14 days."


def _doc(env, document_id):
    return env.client.get(f"/document-library/documents/{document_id}").json()


def _sync(env):
    return env.run(env.service.sync_once())


def test_tier_policy_by_type_and_priority():
    pdf, docx, png = "application/pdf", docx_mime(), "image/png"
    assert [tier_for(m, Priority.BACKGROUND) for m in (pdf, docx, png)] == ["basic", "flash", "basic"]
    assert [tier_for(m, Priority.NORMAL) for m in (pdf, docx, png)] == ["basic", "flash", "basic"]
    assert [tier_for(m, Priority.INTERACTIVE) for m in (pdf, docx, png)] == ["standard"] * 3


def docx_mime() -> str:
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_upload_submits_the_original_and_the_state_follows_the_worker_to_ready(backend):
    backend.engine.parse_status = "pending"
    created = backend.upload(PAGES, "Policy.pdf").json()
    assert created["state"] == "queued" and created["tier"] == "basic" and "backend" not in created  # submitted at once, not yet parsed
    assert _sync(backend) == 0 and _doc(backend, created["id"])["state"] == "queued"
    backend.engine.docs[sha(PAGES)]["status"] = "parsing"
    assert _sync(backend) == 1 and _doc(backend, created["id"])["state"] == "processing"
    backend.engine.docs[sha(PAGES)]["status"] = "done"
    assert _sync(backend) == 1
    final = _doc(backend, created["id"])
    assert (final["state"], final["page_count"], final["error_code"]) == ("ready", 2, None)
    stored = backend.run(backend.store.get(created["id"]))
    assert stored.backend_ref == sha(PAGES)[:7] and stored.backend_revision == sha(PAGES)  # the opaque pointer and the revision it was parsed from
    assert _sync(backend) == 0  # a ready document is no longer polled
    assert [c for c in backend.switch.calls if c[1].endswith("/status")] == [("GET", f"/documents/{created['id']}/status")] * 3


def test_a_worker_that_is_down_leaves_the_document_uploaded_and_the_loop_submits_it_later(backend):
    backend.switch.down = True
    created = backend.upload(PAGES).json()
    assert created["state"] == "uploaded" and backend.engine.docs == {}
    assert _sync(backend) == 0 and _doc(backend, created["id"])["state"] == "uploaded"  # still down: nothing lost, nothing failed
    backend.switch.down = False
    assert _sync(backend) == 1 and _doc(backend, created["id"])["state"] == "ready"


def test_a_refused_document_fails_with_a_code_and_reprocess_can_retry_it_at_another_tier(monkeypatch, tmp_path):
    engine = FakeEngine()
    switch = Switch(create_worker_app(WorkerSettings(token=TOKEN, work_dir=tmp_path / "worker", tiers=("flash",)), engine))  # this worker only runs Flash
    client = DocumentWorkerClient("http://worker", TOKEN, client=httpx.AsyncClient(transport=switch, base_url="http://worker"))
    with Env(monkeypatch, tmp_path, worker=client) as env:
        created = env.upload(PAGES).json()  # a PDF wants Basic
        assert (created["state"], created["error_code"]) == ("failed", "tier_not_enabled")
        assert _sync(env) == 0  # failed is terminal for the loop
        retried = env.client.post(f"/document-library/documents/{created['id']}/reprocess", json={"tier": "flash"}).json()
        assert retried["state"] == "ready" and retried["tier"] == "flash" and retried["error_code"] is None
        assert len(env.client.get("/document-library/documents").json()) == 1  # the same document, not a second one


def test_reprocess_parses_the_retained_original_again_for_the_same_document(backend):
    created = backend.upload(PAGES).json()
    before = backend.run(backend.store.get(created["id"]))
    backend.engine.parse_status = "pending"
    again = backend.client.post(f"/document-library/documents/{created['id']}/reprocess").json()
    assert again["id"] == created["id"] and again["state"] == "queued"
    assert backend.engine.invalidated == [(before.backend_ref, "basic")]  # the cached parse for these bytes was dropped, not patched
    backend.engine.docs[sha(PAGES)]["status"] = "done"
    assert _sync(backend) == 1 and _doc(backend, created["id"])["state"] == "ready"
    assert backend.client.post("/document-library/documents/nope/reprocess").status_code == 404


def test_reprocess_needs_a_usable_original_and_a_worker(monkeypatch, tmp_path, backend):
    created = backend.upload(PAGES).json()
    path = backend.sources.path_for(created["source_hash"])
    path.chmod(0o640)
    path.write_bytes(b"tampered")
    assert backend.client.post(f"/document-library/documents/{created['id']}/reprocess").status_code == 409
    with Env(monkeypatch, tmp_path / "other", worker=None) as bare:
        doc = bare.upload(PAGES).json()
        assert bare.client.post(f"/document-library/documents/{doc['id']}/reprocess").status_code == 503


def test_a_tampered_original_is_never_sent_to_the_worker(backend):
    backend.switch.down = True
    created = backend.upload(PAGES).json()
    path = backend.sources.path_for(created["source_hash"])
    path.chmod(0o640)
    path.write_bytes(b"tampered")
    backend.switch.down, backend.switch.calls = False, []
    assert _sync(backend) == 1
    held = _doc(backend, created["id"])
    assert (held["state"], held["error_code"]) == ("failed", "source_corrupt") and backend.switch.calls == [] and backend.engine.docs == {}


def test_a_worker_that_lost_the_document_is_given_it_again_from_the_authoritative_original(backend, tmp_path):
    created = backend.upload(PAGES).json()
    backend.engine.parse_status = "pending"
    backend.run(backend.service.reprocess(created["id"]))  # back to a state the loop watches
    assert _doc(backend, created["id"])["state"] == "queued"
    backend.engine.docs.clear()  # the worker's library and working copies were rebuilt from nothing ...
    import shutil

    shutil.rmtree(tmp_path / "worker", ignore_errors=True)
    backend.engine.parse_status = "done"
    assert _sync(backend) == 1 and _doc(backend, created["id"])["state"] == "ready"  # ... and the original rebuilt the derived state
    assert backend.engine.docs


def test_read_and_search_go_through_the_reachy_id_and_say_what_kind_of_evidence_they_are(backend):
    created = backend.upload(PAGES, "Policy.pdf").json()
    read = backend.client.get(f"/document-library/documents/{created['id']}/read", params={"page_range": "2"}).json()
    assert "audit period" in read["content"] and read["evidence_type"] == "derived_extraction" and read["source_hash"] == sha(PAGES) and read["title"] == "Policy"
    assert read["start"].endswith("/page:2") and "backend_ref" not in read
    found = backend.client.post(f"/document-library/documents/{created['id']}/search", json={"query": "retention"}).json()
    assert found["evidence_type"] == "derived_extraction" and found["complete"] is True
    assert [(h["page"], h["snippet"]) for h in found["hits"]] == [(1, "The retention requirement is 7 days.")]
    around = backend.client.get(f"/document-library/documents/{created['id']}/locator", params={"locator": found["hits"][0]["locator"]})
    assert around.status_code == 200 and "backend_ref" not in around.text and str(backend.sources.root) not in around.text
    bad = backend.client.get(f"/document-library/documents/{created['id']}/locator", params={"locator": "doc:ffffff0/tier:basic/page:1"})
    assert bad.status_code == 404
    assert backend.client.get("/document-library/documents/nope/read").status_code == 404
    assert backend.client.get(f"/document-library/documents/{created['id']}/read", params={"page_range": "1;x"}).status_code == 422


def test_content_is_refused_until_the_document_is_processed(backend):
    backend.engine.parse_status = "pending"
    created = backend.upload(PAGES).json()
    for call in (
        lambda: backend.client.get(f"/document-library/documents/{created['id']}/read"),
        lambda: backend.client.post(f"/document-library/documents/{created['id']}/search", json={"query": "x"}),
    ):
        assert call().status_code == 409
    assert [c for c in backend.switch.calls if c[1].endswith(("/read", "/search"))] == []


def test_policy_is_checked_from_the_reachy_record_before_every_worker_call(backend):
    restricted = backend.upload(PAGES, sensitivity="sensitive").json()
    shared = backend.upload(PAGES, sensitivity="public").json()  # identical bytes, same backend object, different policy
    backend.switch.calls = []
    for call in (
        lambda: backend.client.get(f"/document-library/documents/{restricted['id']}/read"),
        lambda: backend.client.get(f"/document-library/documents/{restricted['id']}/locator", params={"locator": "doc:abc1234/tier:basic/page:1"}),
        lambda: backend.client.post(f"/document-library/documents/{restricted['id']}/search", json={"query": "retention"}),
    ):
        r = call()
        assert r.status_code == 403 and "retention" not in r.text
    assert backend.switch.calls == []  # the worker was never asked
    assert backend.client.get(f"/document-library/documents/{shared['id']}/read").status_code == 200
    # narrowing the owner's context cannot be undone by the document: a project-scoped context excludes other projects
    from companion_core.semantic.access import access_for_owner

    scoped = backend.upload(PAGES, project_scope="Alpha", title="Scoped").json()
    inside = access_for_owner("owner", channel_private=True, project_scopes=frozenset({"Alpha"}))
    outside = access_for_owner("owner", channel_private=True, project_scopes=frozenset({"Beta"}))
    public_only = access_for_owner("owner", channel_private=False)
    assert backend.run(backend.service.read(scoped["id"], inside)).title == "Scoped"
    for denied in (outside, public_only):
        with pytest.raises(Exception) as exc:
            backend.run(backend.service.read(scoped["id"], denied))
        assert getattr(exc.value, "status", None) == 403


def test_a_document_being_deleted_is_neither_synced_nor_readable(backend):
    backend.switch.down = True
    created = backend.upload(PAGES).json()
    backend.run(backend.store.begin_delete(created["id"], backend.service.clock()))
    backend.switch.down, backend.switch.calls = False, []
    assert _sync(backend) == 0 and backend.switch.calls == [] and backend.engine.docs == {}  # not submitted, not revived
    assert backend.client.get(f"/document-library/documents/{created['id']}/read").status_code == 404
    assert backend.run(backend.service.finish_deletions()) == 1


def test_the_sync_loop_runs_the_same_pass_and_stops_cleanly(backend):
    from companion_core.document_library.service import run_sync_loop

    backend.switch.down = True
    created = backend.upload(PAGES).json()
    backend.switch.down = False

    async def go():
        task = asyncio.create_task(run_sync_loop(backend.service, 0.01))
        for _ in range(100):
            if (await backend.store.get(created["id"])).state is DocumentState.READY:
                break
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    backend.run(go())
    assert _doc(backend, created["id"])["state"] == "ready"


def test_reprocessing_one_document_does_not_break_another_with_the_same_bytes(backend):
    """Found with the real MinerU: identical bytes share one backend document, and invalidating all of its tiers took the other document's parse away while it still said READY."""
    first = backend.upload(PAGES, title="First").json()
    second = backend.upload(PAGES, title="Second").json()
    backend.client.post(f"/document-library/documents/{first['id']}/reprocess", json={"tier": "standard"})
    assert backend.engine.invalidated[-1][1] == "standard"  # only the tier being rebuilt was dropped, never the other document's tier
    # and when a shared parse does go missing, a stale READY is corrected instead of staying wrong
    backend.engine.docs[sha(PAGES)]["status"] = "pending"
    r = backend.client.get(f"/document-library/documents/{second['id']}/read")
    assert r.status_code == 409 and _doc(backend, second["id"])["state"] == "queued"
    backend.engine.docs[sha(PAGES)]["status"] = "done"
    assert _sync(backend) >= 1 and _doc(backend, second["id"])["state"] == "ready"
    assert backend.client.get(f"/document-library/documents/{second['id']}/read").status_code == 200
