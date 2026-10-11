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
from companion_core.document_library.models import DocumentState
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
    """The 50A behaviours that matter for deletion: identity is the content hash, identical bytes share one backend document, forgetting a file leaves the document until orphans are cleaned."""

    def __init__(self):
        self.docs: dict[str, set[str]] = {}
        self.fail = False

    def health(self):
        return EngineHealth(True, True)

    def ensure_parse(self, path, tier, page_range, force):
        digest = sha(path.read_bytes())
        self.docs.setdefault(digest, set()).add(str(path))
        return Ticket(digest, digest[:7])

    def parse_summary(self, ref, tier):
        return ParseSummary(("done",))

    def page_count(self, ref):
        return 1

    def read(self, *a, **k):
        return RawContent("")

    read_locator = read

    def search(self, *a, **k):
        return [], 0

    def invalidate(self, ref):
        pass

    def forget(self, path):
        if self.fail:
            raise EngineError("engine_unavailable")
        for files in self.docs.values():
            files.discard(str(path))

    def cleanup_orphans(self):
        for digest in [d for d, files in self.docs.items() if not files]:
            del self.docs[digest]

    def has_active_files(self, ref):
        return any(files for digest, files in self.docs.items() if digest.startswith(ref))


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
            document_store=self.store if enabled else None, document_sources=self.sources if enabled else None, document_worker=worker,
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
    worker_app = create_worker_app(WorkerSettings(token=TOKEN, work_dir=tmp_path / "worker"), engine)
    client = DocumentWorkerClient("http://worker", TOKEN, client=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_app), base_url="http://worker"))
    with Env(monkeypatch, tmp_path, worker=client) as env:
        env.engine, env.worker = engine, client
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
