"""Phase 50B on real PostgreSQL (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector): migration 031 and its rollback script, the structural guarantees, and the
real store behind the real routes. Synthetic data only."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from companion_core.document_library.models import Document, DocumentState
from companion_core.document_library.postgres_store import PostgresDocumentStore
from companion_core.migrations.__main__ import upgrade
from companion_core.secrets import Keyring

from shared.models.response import Privacy

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
KEYS = Keyring("one", {"one": b"\x01" * 32})
ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-031.sql"
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
HASH = "a" * 64


@pytest.fixture
def dsn():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    url = psycopg.conninfo.make_conninfo(root, dbname=name)
    upgrade(url, KEYS)
    try:
        yield url
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def sql(dsn, query, params=None):
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def doc(**over) -> Document:
    base = {"title": "Spec", "filename": "spec.pdf", "mime_type": "application/pdf", "source_hash": HASH, "size_bytes": 10, "created_at": NOW, "updated_at": NOW}
    return Document(**{**base, **over})


def test_the_migration_adds_one_table_with_structural_guarantees(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("031_documents",)]
    assert sql(dsn, "SELECT count(*) FROM pg_tables WHERE tablename = 'documents'") == [(1,)]
    assert sql(dsn, "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'documents'::regclass AND NOT tgisinternal") == [(0,)]  # nothing reaches the index or outbox
    assert sql(dsn, "SELECT count(*) FROM pg_constraint WHERE conrelid = 'documents'::regclass AND contype = 'f'") == [(0,)]
    base = "INSERT INTO documents (id, title, filename, mime_type, source_hash, size_bytes, sensitivity, state, processing_priority, created_at, updated_at) VALUES (%s,'t','f','m',%s,%s,%s,%s,%s,now(),now())"
    sql(dsn, base, ("one", HASH, 1, "public", "uploaded", "background"))
    sql(dsn, base, ("two", HASH, 1, "sensitive", "ready", "normal"))  # identical bytes are allowed twice: the hash is indexed, not unique
    for bad in (("x", "short", 1, "public", "uploaded", "background"), ("x", HASH, 0, "public", "uploaded", "background"), ("x", HASH, 1, "secret", "uploaded", "background"),
                ("x", HASH, 1, "public", "archived", "background"), ("x", HASH, 1, "public", "uploaded", "urgent")):
        with pytest.raises(psycopg.errors.CheckViolation):
            sql(dsn, base, bad)


def test_the_rollback_script_drops_only_the_catalogue_and_the_migration_can_run_again(dsn):
    sql(dsn, "INSERT INTO notes (id, title, body, created_at, updated_at, sensitivity) VALUES ('n1','t','b',now(),now(),'work-private')")
    sql(dsn, "INSERT INTO documents (id, title, filename, mime_type, source_hash, size_bytes, sensitivity, state, processing_priority, created_at, updated_at) VALUES ('d','t','f','m',%s,1,'public','uploaded','background',now(),now())", (HASH,))
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK.read_text())
        conn.commit()
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("030_note_tags",)]
    assert sql(dsn, "SELECT count(*) FROM pg_tables WHERE tablename = 'documents'") == [(0,)]
    assert sql(dsn, "SELECT count(*) FROM notes") == [(1,)]
    upgrade(dsn, KEYS)
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("031_documents",)] and sql(dsn, "SELECT count(*) FROM documents") == [(0,)]


def test_the_real_store_keeps_a_deleting_document_deleting(dsn):
    async def go():
        store = await PostgresDocumentStore.connect(dsn)
        try:
            a, b = doc(sensitivity=Privacy.SENSITIVE, project_scope="Alpha"), doc()
            await store.add(a)
            await store.add(b)
            assert (await store.get(a.id)) == a and {d.id for d in await store.list()} == {a.id, b.id}
            assert await store.count_by_hash(HASH) == 2
            moved = await store.update(a.id, NOW, state=DocumentState.READY, backend_ref="abc1234", tier="basic", page_count=3, title="New")
            assert (moved.state, moved.backend_ref, moved.page_count, moved.title, moved.sensitivity, moved.project_scope) == (DocumentState.READY, "abc1234", 3, "New", Privacy.SENSITIVE, "Alpha")
            with pytest.raises(ValueError):
                await store.update(a.id, NOW, source_hash="b" * 64)  # the hash and id are not updatable
            assert [d.id for d in await store.pending_sync()] == [b.id]  # b is `uploaded`; a is ready, then deleting: neither is polled
            assert (await store.begin_delete(a.id, NOW)).state is DocumentState.DELETING
            assert (await store.begin_delete(a.id, NOW)).state is DocumentState.DELETING  # idempotent
            assert await store.update(a.id, NOW, state=DocumentState.READY) is None  # it cannot be revived
            assert [d.id for d in await store.deleting()] == [a.id]
            assert await store.remove(a.id) and not await store.remove(a.id)
            assert await store.count_by_hash(HASH) == 1 and await store.begin_delete("nope", NOW) is None
        finally:
            await store.close()

    asyncio.run(go())


def test_the_service_lifecycle_runs_on_the_real_store(dsn, tmp_path):
    """Found at the gate drill: the service updates `backend`, which the PostgreSQL store refused while the in-memory twin accepted it."""
    import httpx
    from companion_core.document_library.models import Priority
    from companion_core.document_library.service import DocumentService
    from companion_core.document_library.source_store import SourceStore
    from companion_core.document_library.worker_client import DocumentWorkerClient

    state = {"worker": "queued"}

    def worker(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"document_id": "x", "deleted": True, "verified": True, "shared_hash_remaining": False})
        doc_id = request.url.path.split("/")[2] if request.url.path.count("/") > 1 else "x"
        return httpx.Response(200, json={"document_id": doc_id, "backend": "mineru", "backend_ref": "abc1234", "source_hash": HASH, "tier": "basic", "state": state["worker"], "page_count": 2})

    async def chunks():
        yield b"%PDF-1.4\nbody"

    async def go():
        store = await PostgresDocumentStore.connect(dsn)
        client = DocumentWorkerClient("http://w", "t", client=httpx.AsyncClient(transport=httpx.MockTransport(worker), base_url="http://w"))
        service = DocumentService(store, SourceStore(tmp_path / "src"), client)
        try:
            doc = await service.upload("a.pdf", chunks(), priority=Priority.NORMAL)
            assert (doc.state, doc.backend_ref, doc.backend, doc.tier) == (DocumentState.QUEUED, "abc1234", "mineru", "basic")
            state["worker"] = "ready"
            assert await service.sync_once() == 1
            ready = await store.get(doc.id)
            assert (ready.state, ready.page_count) == (DocumentState.READY, 2)
            await service.delete(doc.id)
            assert await store.list() == []
        finally:
            await client.close()
            await store.close()

    asyncio.run(go())


def test_derived_outputs_on_the_real_store(dsn):
    from companion_core.document_library.models import DocumentOutput, OutputStatus

    async def go():
        store = await PostgresDocumentStore.connect(dsn)
        try:
            d = doc()
            await store.add(d)
            first = DocumentOutput(document_id=d.id, kind="summary", style="executive", source_hash=HASH, tier="basic", sensitivity=Privacy.SENSITIVE, created_at=NOW, updated_at=NOW)
            got, created = await store.begin_output(first)
            assert created and got.id == first.id
            again, created = await store.begin_output(DocumentOutput(document_id=d.id, kind="summary", style="executive", source_hash=HASH, tier="basic", sensitivity=Privacy.SENSITIVE))
            assert not created and again.id == first.id  # one current output per document, kind and style
            other, created = await store.begin_output(DocumentOutput(document_id=d.id, kind="summary", style="technical", source_hash=HASH, tier="basic", sensitivity=Privacy.SENSITIVE))
            assert created
            done = await store.finish_output(first.id, NOW, status=OutputStatus.READY, text="body", sections=({"pages": "1", "start_page": 1, "end_page": 1, "summary": "s", "locator": None},), pages_covered="1", page_count=1, model="m")
            assert (done.status, done.text, done.sections[0]["summary"], done.sensitivity) == (OutputStatus.READY, "body", "s", Privacy.SENSITIVE)
            with pytest.raises(ValueError):
                await store.finish_output(first.id, NOW, source_hash="b" * 64)
            assert await store.supersede_outputs(d.id, NOW, kind="summary", style="executive") == 1
            replacement, created = await store.begin_output(DocumentOutput(document_id=d.id, kind="summary", style="executive", source_hash=HASH, tier="standard", sensitivity=Privacy.SENSITIVE))
            assert created and replacement.id != first.id and (await store.get_output(first.id)).stale
            assert await store.fail_running_outputs(NOW) == 2  # the technical and the replacement were still running
            assert {o.error_code for o in await store.list_outputs(d.id) if o.status is OutputStatus.FAILED} == {"interrupted"}
            assert len(await store.list_outputs(d.id)) == 3 and other.id
            assert await store.delete_outputs(d.id) == 3 and await store.list_outputs(d.id) == []
        finally:
            await store.close()

    asyncio.run(go())
