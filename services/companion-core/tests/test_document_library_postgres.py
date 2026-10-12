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
