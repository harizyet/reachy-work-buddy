"""Phase 44B on real Postgres (opt-in: DATABASE_MIGRATION_TEST_URL must be a disposable server with pgvector): migration 027, the
triggers that fill the outbox in the source's own transaction, immediate exclusion on forget/delete/cancel, the worker against the
real stores and index, concurrent workers, crash recovery, the generation guard, reconciliation of a damaged index, and revalidation
against a stale index. In-memory counterparts of the logic live in test_knowledge_index.py."""

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from companion_core.knowledge.index import PostgresKnowledgeIndex
from companion_core.knowledge.outbox import MAX_ATTEMPTS, PostgresOutbox
from companion_core.knowledge.revalidate import Candidate, revalidate
from companion_core.knowledge.sources import build_adapters
from companion_core.knowledge.worker import IndexingWorker
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.migrations import __main__ as migrations
from companion_core.migrations.__main__ import upgrade
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.secrets import Keyring
from companion_core.semantic.model import AccessContext, SourceRef
from companion_core.tasks.postgres_store import PostgresTaskStore
from psycopg.types.json import Json
from sqlalchemy import create_engine

from shared.database import SCHEMA_REVISION
from shared.models.response import Privacy

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector"
)
KEYS = Keyring("one", {"one": b"\x01" * 32})


def embed(texts):
    out = []
    for text in texts:
        vector = [0.0] * 384
        for word in text.lower().split():
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        out.append([v / norm for v in vector] if norm else vector)
    return out


@pytest.fixture
def database():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    try:
        yield psycopg.conninfo.make_conninfo(root, dbname=name)
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def upgrade_to(dsn: str, revision: str) -> None:
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), hide_parameters=True)
    try:
        with engine.begin() as conn:
            config = Config()
            config.set_main_option("script_location", str(Path(migrations.__file__).parent))
            config.attributes.update(connection=conn, keyring=KEYS, adopt_legacy=False)
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def sql(dsn, query, params=()):
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.execute(query, params or None)
        return cur.fetchall() if cur.description else None


def outbox_rows(dsn):
    return {(r[0], r[1]): (r[2], r[3]) for r in sql(dsn, "SELECT source_type, source_id, gen, failed_at FROM knowledge_outbox")}


class Stack:
    """The real Postgres stores, adapters, index, outbox and a worker, on a freshly migrated database."""

    async def open(self, dsn, tmp_path):
        self.dsn = dsn
        self.memory, self.planner = await PostgresMemoryStore.connect(dsn), await PostgresPlannerStore.connect(dsn)
        self.tasks, self.documents = await PostgresTaskStore.connect(dsn), await PostgresDocumentStore.connect(dsn, embed_fn=embed)
        self.meetings = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        self.index, self.outbox = await PostgresKnowledgeIndex.connect(dsn), await PostgresOutbox.connect(dsn)
        self.adapters = build_adapters(
            memory=self.memory, documents=self.documents, meetings=self.meetings, planner=self.planner, tasks=self.tasks
        )
        self.worker = IndexingWorker(
            adapters=self.adapters, index=self.index, outbox=self.outbox, embed_fn=embed, embedding_model="test-model"
        )
        return self

    async def close(self):
        for part in (self.memory, self.planner, self.tasks, self.documents, self.meetings, self.index, self.outbox):
            await part.close()

    async def meeting(self, texts, *, scope=None, sensitivity=Privacy.WORK_PRIVATE):
        m = await self.meetings.create_meeting(
            title="Sync", audio=b"x", source_filename="a.wav", content_type="audio/wav", project_scope=scope, sensitivity=sensitivity
        )
        segments = [{"start": float(i), "end": float(i + 1), "text": t} for i, t in enumerate(texts)]
        diar = [{"start": float(i), "end": float(i + 1), "speaker": "SPEAKER_00"} for i in range(len(texts))]
        sql(self.dsn, "UPDATE meetings SET transcript_segments = %s, diarization_segments = %s, status = 'aligning' WHERE id = %s",
            (Json(segments), Json(diar), m.id))
        return m.id


class Env:
    def __init__(self, dsn, tmp):
        self.dsn, self.tmp = dsn, tmp


@pytest.fixture
def env(database, tmp_path):
    upgrade(database, KEYS)
    return Env(database, tmp_path)


def run(coro):
    return asyncio.run(coro)


def run_stack(env, scenario):
    """Open the stores inside the scenario's own event loop (their connection pools belong to it) and always close them."""

    async def wrapper():
        stack = await Stack().open(env.dsn, env.tmp)
        try:
            await scenario(stack)
        finally:
            await stack.close()

    asyncio.run(wrapper())


def ctx(**kw):
    return AccessContext(**{"principal": "o", "sensitivity_ceiling": Privacy.WORK_PRIVATE, **kw})


# ---- migration 027 ----------------------------------------------------------------------------------------------

def test_migration_adds_the_index_the_outbox_and_the_triggers_and_queues_existing_records(database):
    upgrade_to(database, "026_source_sensitivity")
    sql(database, "INSERT INTO notes (id, title, body, created_at, updated_at) VALUES ('n1','t','b',now(),now())")
    sql(database, "INSERT INTO tasks (id, text, status, created_at) VALUES ('t1','do it','open',now())")
    sql(database, "INSERT INTO memories VALUES ('m1','working','fact','s',NULL,1.0,'work-private',now(),NULL,NULL,NULL)")
    sql(database, "INSERT INTO meetings (id, title, source_filename, content_type, audio_path, status) VALUES ('mt1','x','a','b','c','complete')")
    upgrade(database, KEYS)
    assert sql(database, "SELECT version_num FROM alembic_version")[0][0] == SCHEMA_REVISION == "028_memory_candidates"
    assert {r[0] for r in sql(database, "SELECT tgname FROM pg_trigger WHERE tgname LIKE 'knowledge_%'")} == {
        "knowledge_memories", "knowledge_chunks", "knowledge_meetings", "knowledge_notes", "knowledge_tasks", "knowledge_reminders"}
    assert set(outbox_rows(database)) == {("note", "n1"), ("task", "t1"), ("memory", "m1"), ("meeting", "mt1")}
    upgrade(database, KEYS)  # a repeat changes nothing
    assert len(outbox_rows(database)) == 4
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(database, "INSERT INTO knowledge_items (ref_key, source_type, source_id, kind, source_version, match_text, embedding_model, "
                      "sensitivity, local_only, confidence, indexed_at) VALUES ('k','note','n','note','v','t','m','secret',false,1,now())")


def downgrade_to(dsn, revision):
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), hide_parameters=True)
    try:
        with engine.begin() as conn:
            config = Config()
            config.set_main_option("script_location", str(Path(migrations.__file__).parent))
            config.attributes.update(connection=conn, keyring=KEYS, adopt_legacy=False)
            command.downgrade(config, revision)
    finally:
        engine.dispose()


def derived_objects(dsn):
    return {r[0] for r in sql(dsn, "SELECT relname FROM pg_class WHERE relname LIKE 'knowledge_items%' OR relname LIKE 'knowledge_outbox%'")}, {
        r[0] for r in sql(dsn, "SELECT proname FROM pg_proc WHERE proname LIKE 'knowledge_%'")}


@pytest.mark.parametrize("how", ["alembic", "sql_file"])
def test_027_can_be_undone_without_touching_authoritative_data_and_applied_again(database, how):
    upgrade(database, KEYS)
    sql(database, "INSERT INTO notes (id, title, body, created_at, updated_at) VALUES ('n1','t','b',now(),now())")
    sql(database, "INSERT INTO tasks (id, text, status, created_at) VALUES ('t1','x','open',now())")
    assert derived_objects(database)[0] and derived_objects(database)[1]
    if how == "alembic":
        downgrade_to(database, "026_source_sensitivity")
    else:
        for name in ("rollback-028.sql", "rollback-027.sql"):  # the head is 028 now: undo it first, as the runbook would
            script = (Path(__file__).parents[3] / "deploy" / "homelab" / name).read_text()
            with psycopg.connect(database) as conn:
                conn.execute(script)  # one transaction per script, as each script's own instructions require
    assert sql(database, "SELECT version_num FROM alembic_version")[0][0] == "026_source_sensitivity"
    assert derived_objects(database) == (set(), set())
    assert sql(database, "SELECT count(*) FROM notes")[0][0] == 1 and sql(database, "SELECT count(*) FROM tasks")[0][0] == 1
    sql(database, "INSERT INTO notes (id, title, body, created_at, updated_at) VALUES ('n2','t','b',now(),now())")  # no trigger left behind
    upgrade(database, KEYS)
    assert sql(database, "SELECT version_num FROM alembic_version")[0][0] == SCHEMA_REVISION
    assert {("note", "n1"), ("note", "n2"), ("task", "t1")} <= set(outbox_rows(database))  # applied again: everything is queued anew


def test_027_is_safe_to_apply_over_leftovers_from_an_earlier_copy(database):
    """After restoring a dump taken before 027 (whose --clean cannot drop the index tables), the derived tables and functions may
    still exist. Applying the revision again must start clean rather than fail or keep stale rows."""
    upgrade(database, KEYS)
    sql(database, "INSERT INTO knowledge_items (ref_key, source_type, source_id, kind, source_version, match_text, embedding_model, "
                  "sensitivity, local_only, confidence, indexed_at) VALUES ('note:old','note','old','note','v','x','m','public',false,1,now())")
    sql(database, "UPDATE alembic_version SET version_num = '026_source_sensitivity'")
    upgrade(database, KEYS)
    assert sql(database, "SELECT count(*) FROM knowledge_items")[0][0] == 0


# ---- triggers ---------------------------------------------------------------------------------------------------

def test_a_change_to_a_source_queues_it_in_the_same_transaction_and_noise_does_not(env):
    async def go(stack):
        db = stack.dsn
        note = await stack.planner.add_note("A", "body")
        mem = await stack.memory.add_memory(content="a fact", source="s")
        await stack.documents.ingest_document(title="D", content="# S\none\n\n# T\ntwo\n\n# U\nthree", source="s")
        rows = outbox_rows(db)
        assert ("note", note.id) in rows and ("memory", mem.id) in rows and sum(1 for k in rows if k[0] == "document") == 1
        await stack.worker.drain()
        assert outbox_rows(db) == {}
        await stack.memory.recall("fact")  # stamps last_accessed: a read, not a change
        rem = await stack.planner.add_reminder("r", datetime.now(UTC) - timedelta(minutes=1))
        await stack.worker.drain()
        await stack.planner.claim_due(datetime.now(UTC))  # stamps notified_at: not indexed state
        assert outbox_rows(db) == {}
        await stack.planner.update_note(note.id, "A", "changed")
        await stack.planner.update_note(note.id, "A", "changed again")
        assert outbox_rows(db)[("note", note.id)][0] == 2  # coalesced into one row; the generation counts both
        await stack.planner.complete_reminder(rem.id)
        assert ("reminder", rem.id) in outbox_rows(db)

    run_stack(env, go)


def test_a_rolled_back_change_leaves_no_event(env):
    with psycopg.connect(env.dsn) as conn:
        conn.execute("INSERT INTO notes (id, title, body, created_at, updated_at) VALUES ('ghost','t','b',now(),now())")
        assert ("note", "ghost") in {(r[0], r[1]) for r in conn.execute("SELECT source_type, source_id FROM knowledge_outbox").fetchall()}
        conn.rollback()
    assert ("note", "ghost") not in outbox_rows(env.dsn)


def test_forgetting_deleting_or_cancelling_removes_the_index_rows_at_once_without_the_worker(env):
    async def go(stack):
        mem = await stack.memory.add_memory(content="secret handshake", source="s")
        note = await stack.planner.add_note("N", "body")
        task = await stack.tasks.add_task("do it")
        rem = await stack.planner.add_reminder("r", datetime.now(UTC) + timedelta(days=1))
        mid = await stack.meeting(["hello world"])
        cancelled = await stack.meeting(["other talk"])
        deleted = await stack.meeting(["third talk"])
        docs = await stack.documents.ingest_document(title="D", content="# A\none\n\n# B\ntwo", source="s")
        await stack.worker.drain()
        total = await stack.index.count()
        assert total == 1 + 1 + 1 + 1 + 3 + 2
        await stack.memory.forget(mem.id)
        assert await stack.index.get(f"memory:{mem.id}") is None  # gone before any worker ran
        await stack.planner.delete_note(note.id)
        await stack.tasks.delete_task(task.id)
        await stack.planner.delete_reminder(rem.id)
        await stack.meetings.cancel_meeting(cancelled)
        await stack.meetings.delete_meeting(deleted)
        for key in (f"note:{note.id}", f"task:{task.id}", f"reminder:{rem.id}", f"meeting:{cancelled}#0", f"meeting:{deleted}#0"):
            assert await stack.index.get(key) is None, key
        assert await stack.index.get(f"meeting:{mid}#0") is not None  # the others stay
        sql(stack.dsn, "DELETE FROM document_chunks WHERE document_id = %s AND chunk_index = 1", (docs[0].document_id,))
        assert await stack.index.get(f"document:{docs[0].document_id}#1") is None
        assert await stack.index.get(f"document:{docs[0].document_id}#0") is not None
        await stack.memory.restore(mem.id)
        await stack.worker.drain()
        assert await stack.index.get(f"memory:{mem.id}") is not None  # undo: restoring queues it again

    run_stack(env, go)


# ---- the worker on real stores ----------------------------------------------------------------------------------

def test_the_worker_builds_the_index_from_real_stores_with_embeddings_and_search_columns(env):
    async def go(stack):
        await stack.planner.add_note("Falcon", "falcon seven bee benchmark", project_scope="harbor")
        await stack.memory.add_memory(content="queue retries five", source="s", sensitivity=Privacy.SENSITIVE)
        await stack.worker.drain()
        row = await stack.index.get(f"note:{(await stack.planner.list_notes())[0].id}")
        assert row.project_scope == "harbor" and row.embedding_model == "test-model" and row.local_only is False
        near = sql(stack.dsn, "SELECT ref_key FROM knowledge_items ORDER BY embedding <=> %s::vector LIMIT 1", (str(embed(["falcon benchmark"])[0]),))
        assert near[0][0].startswith("note:")
        assert sql(stack.dsn, "SELECT count(*) FROM knowledge_items WHERE tsv @@ plainto_tsquery('english', 'falcon')")[0][0] == 1
        assert sql(stack.dsn, "SELECT count(*) FROM knowledge_items WHERE embedding IS NULL")[0][0] == 0
        mem_row = next(r for r in sql(stack.dsn, "SELECT sensitivity FROM knowledge_items WHERE source_type = 'memory'"))
        assert mem_row[0] == "sensitive"

    run_stack(env, go)


def test_concurrent_workers_sync_each_source_exactly_once(env):
    async def go(stack):
        notes = [await stack.planner.add_note(f"N{i}", f"body {i}") for i in range(24)]
        other = IndexingWorker(adapters=stack.adapters, index=stack.index, outbox=stack.outbox, embed_fn=embed,
                               embedding_model="test-model", batch=4)
        stack.worker.batch = 4
        a, b = await asyncio.gather(stack.worker.drain(), other.drain())
        assert a.processed + b.processed == 24 and a.failed == b.failed == 0
        assert await stack.index.count() == 24 and outbox_rows(stack.dsn) == {}
        assert len({n.id for n in notes}) == 24

    run_stack(env, go)


def test_a_crashed_claim_is_retried_after_the_lease_and_a_concurrent_change_is_not_lost(env):
    async def go(stack):
        note = await stack.planner.add_note("A", "first")
        now = datetime.now(UTC)
        (claimed,) = await stack.outbox.claim(now, lease_seconds=300, limit=5)  # a worker claims it and dies
        assert await stack.outbox.claim(now + timedelta(seconds=10), lease_seconds=300, limit=5) == []
        (again,) = await stack.outbox.claim(now + timedelta(seconds=301), lease_seconds=300, limit=5)
        assert again.id == claimed.id
        await stack.planner.update_note(note.id, "A", "second")  # changes mid-sync: the trigger bumps the generation
        assert await stack.outbox.complete(again, datetime.now(UTC)) is False
        assert ("note", note.id) in outbox_rows(stack.dsn)
        await stack.worker.drain()
        assert "second" in (await stack.index.get(f"note:{note.id}")).match_text and outbox_rows(stack.dsn) == {}

    run_stack(env, go)


def test_failures_back_off_set_aside_and_are_revived_by_a_change(env):
    async def go(stack):
        sql(stack.dsn, "INSERT INTO knowledge_outbox (source_type, source_id) VALUES ('bogus', 'x')")
        base = datetime.now(UTC)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            stack.worker.clock = lambda a=attempt: base + timedelta(days=a)
            assert (await stack.worker.run_once()).failed == 1
        status = await stack.outbox.status(base + timedelta(days=20))
        assert (status.pending, status.failed) == (0, 1)
        stack.worker.clock = lambda: base + timedelta(days=40)
        assert (await stack.worker.run_once()).processed == 0
        sql(stack.dsn, "SELECT knowledge_enqueue('bogus', 'x')")
        assert outbox_rows(stack.dsn)[("bogus", "x")][1] is None  # revived
        assert (await stack.worker.run_once()).processed == 1
        assert sql(stack.dsn, "SELECT last_error FROM knowledge_outbox")[0][0].startswith("ValueError")

    run_stack(env, go)


def test_reconcile_repairs_deleted_stale_and_orphaned_rows(env):
    async def go(stack):
        a = await stack.planner.add_note("A", "alpha")
        b = await stack.planner.add_note("B", "beta")
        await stack.worker.drain()
        sql(stack.dsn, "DELETE FROM knowledge_items WHERE ref_key = %s", (f"note:{a.id}",))
        sql(stack.dsn, "UPDATE knowledge_items SET source_version = 'old' WHERE ref_key = %s", (f"note:{b.id}",))
        sql(stack.dsn, "INSERT INTO knowledge_items (ref_key, source_type, source_id, kind, source_version, match_text, embedding_model, "
                       "sensitivity, local_only, confidence, indexed_at) VALUES ('note:ghost','note','ghost','note','v','x','m','public',false,1,now())")
        report = await stack.worker.reconcile()
        assert (report.enqueued, report.orphans_deleted) == (2, 1)
        await stack.worker.drain()
        assert await stack.index.count() == 2 and await stack.index.get("note:ghost") is None
        assert (await stack.worker.reconcile()).enqueued == 0

    run_stack(env, go)


# ---- revalidation against a stale Postgres index ----------------------------------------------------------------

def test_revalidation_holds_against_a_stale_index_on_real_stores(env):
    async def go(stack):
        mem = await stack.memory.add_memory(content="current fact", source="s", expires_at=datetime.now(UTC) + timedelta(hours=1))
        note = await stack.planner.add_note("Actions", "original text", project_scope="harbor")
        mid = await stack.meeting(["retries are five"], scope="harbor")
        await stack.worker.drain()
        candidates = [
            Candidate(SourceRef(source_type="memory", source_id=mem.id)),
            Candidate(SourceRef(source_type="note", source_id=note.id)),
            Candidate(SourceRef(source_type="meeting", source_id=mid, locator="0")),
        ]
        ok = await revalidate(candidates, ctx(), stack.adapters)
        assert len(ok.items) == 3 and ok.local_only
        # the worker stops; the sources move on in ways the index has not seen
        sql(stack.dsn, "UPDATE notes SET body = 'edited by hand', sensitivity = 'sensitive' WHERE id = %s", (note.id,))
        sql(stack.dsn, "UPDATE memories SET expires_at = now() - interval '1 second' WHERE id = %s", (mem.id,))
        stale_note = await stack.index.get(f"note:{note.id}")
        assert stale_note.sensitivity == Privacy.WORK_PRIVATE and "original" in stale_note.match_text
        bundle = await revalidate(candidates, ctx(), stack.adapters)
        assert [i.ref.source_type for i in bundle.items] == ["meeting"] and bundle.dropped == {"expired": 1, "over_ceiling": 1}
        wide = await revalidate(candidates, ctx(sensitivity_ceiling=Privacy.SENSITIVE), stack.adapters)
        note_item = next(i for i in wide.items if i.ref.source_type == "note")
        assert note_item.text.endswith("edited by hand") and note_item.sensitivity == Privacy.SENSITIVE
        await stack.meetings.delete_meeting(mid)
        gone = await revalidate(candidates[2:], ctx(), stack.adapters)
        assert gone.items == [] and gone.dropped == {"missing": 1}

    run_stack(env, go)


def test_the_background_loop_keeps_the_index_in_step_and_stops_cleanly(env):
    from companion_core.knowledge.runtime import start_indexing

    async def go():
        memory, planner = await PostgresMemoryStore.connect(env.dsn), await PostgresPlannerStore.connect(env.dsn)
        tasks, documents = await PostgresTaskStore.connect(env.dsn), await PostgresDocumentStore.connect(env.dsn, embed_fn=embed)
        meetings = await PostgresMeetingStore.connect(env.dsn, audio_dir=env.tmp)
        handle = await start_indexing(
            dsn=env.dsn, memory=memory, documents=documents, meetings=meetings, planner=planner, tasks=tasks,
            embed_fn=embed, embedding_model="loop-model", interval=0.05, reconcile_every=3600,
        )
        try:
            note = await planner.add_note("Loop", "indexed in the background")

            async def appears(key, present=True):
                for _ in range(100):
                    if (await handle.worker.index.get(key) is not None) == present:
                        return True
                    await asyncio.sleep(0.05)
                return False

            assert await appears(f"note:{note.id}")
            await planner.delete_note(note.id)
            assert await appears(f"note:{note.id}", present=False)
        finally:
            await handle.stop()
            for part in (memory, planner, tasks, documents, meetings):
                await part.close()
        assert handle.task.done()

    asyncio.run(go())


def test_the_real_application_write_paths_keep_the_index_right(env):
    """Through core's HTTP API (the paths the web UI, the apps and Telegram use), with the Postgres stores, the triggers and a worker:
    what each write does to the index, and how fast the exclusions take effect."""
    import httpx
    from companion_core.app import create_app
    from companion_core.calendar.store import InMemoryCalendarStore
    from companion_core.consent.store import InMemoryConfirmationStore
    from companion_core.email.store import InMemoryEmailStore
    from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
    from companion_core.persona.store import InMemoryPersonaStore
    from companion_core.websearch.store import InMemorySearchSettingsStore

    async def go(stack):
        app = create_app(
            calendar_store=InMemoryCalendarStore(), task_store=stack.tasks, planner_store=stack.planner, meeting_store=stack.meetings,
            run_meeting_worker_task=False, memory_store=stack.memory, rag_store=stack.documents, email_store=InMemoryEmailStore(),
            confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(),
            llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
            search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        )
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://core")
        index = stack.index

        async def present(key):
            return await index.get(key) is not None

        async def match(key):
            row = await index.get(key)
            return row.match_text if row else None

        # notes: create, edit, delete
        note = (await client.post("/notes", json={"title": "Plan", "body": "alpha zebra"})).json()
        await stack.worker.drain()
        assert "zebra" in await match(f"note:{note['id']}")
        await client.put(f"/notes/{note['id']}", json={"title": "Plan", "body": "alpha giraffe"})
        await stack.worker.drain()
        assert "giraffe" in await match(f"note:{note['id']}")
        assert (await client.delete(f"/notes/{note['id']}")).status_code == 200
        assert not await present(f"note:{note['id']}")  # gone with no worker pass in between

        # memories: forgetting is a two-step flow and removes the row at once; restoring brings it back
        mem = (await client.post("/memories", json={"content": "quartz is the codeword", "source": "api"})).json()
        await stack.worker.drain()
        assert await present(f"memory:{mem['id']}")
        pending = (await client.post(f"/memories/{mem['id']}/request-forget")).json()
        assert await present(f"memory:{mem['id']}")  # requesting a confirmation changes nothing
        assert (await client.post(f"/memories/{mem['id']}/forget/confirm", json={"confirmation_id": pending["id"]})).status_code == 200
        assert not await present(f"memory:{mem['id']}")
        assert (await client.post(f"/memories/{mem['id']}/restore")).status_code == 200
        await stack.worker.drain()
        assert await present(f"memory:{mem['id']}")

        # tasks: classification is carried; completing changes the indexed text; deleting removes the row
        task = (await client.post("/tasks", json={"text": "ship it", "sensitivity": "sensitive", "project_scope": "harbor"})).json()
        await stack.worker.drain()
        row = await index.get(f"task:{task['id']}")
        assert (row.sensitivity, row.project_scope) == (Privacy.SENSITIVE, "harbor")
        await client.post(f"/tasks/{task['id']}/complete")
        await stack.worker.drain()
        assert "(done" in await match(f"task:{task['id']}")
        await client.delete(f"/tasks/{task['id']}")
        assert not await present(f"task:{task['id']}")

        # documents: ingestion indexes every chunk with its classification
        chunks = (await client.post("/documents", json={"title": "Guide", "content": "# One\nfirst\n\n# Two\nsecond", "sensitivity": "public"})).json()
        await stack.worker.drain()
        doc = chunks[0]["document_id"]
        assert [await present(f"document:{doc}#{i}") for i in (0, 1)] == [True, True]
        assert (await index.get(f"document:{doc}#0")).sensitivity == Privacy.PUBLIC

        # meetings: a correction reaches the index (not the raw transcript); a reclassification does too; deleting removes everything
        mid = await stack.meeting(["falcon seven bee restarts", "retries are five"], scope="harbor")
        await stack.worker.drain()
        assert (await client.put(f"/meetings/{mid}/corrections/0", json={"text": "Falcon-7B restarts"})).status_code == 200
        await stack.worker.drain()
        assert "Falcon-7B" in await match(f"meeting:{mid}#0")
        assert sql(stack.dsn, "SELECT transcript_segments->0->>'text' FROM meetings WHERE id = %s", (mid,))[0][0] == "falcon seven bee restarts"
        sql(stack.dsn, "UPDATE meetings SET status = 'complete' WHERE id = %s", (mid,))
        await stack.worker.drain()
        sql(stack.dsn, "UPDATE meetings SET sensitivity = 'sensitive' WHERE id = %s", (mid,))
        stale = await index.get(f"meeting:{mid}#1")
        assert stale.sensitivity == Privacy.WORK_PRIVATE  # the worker has not run yet...
        bundle = await revalidate([Candidate(SourceRef(source_type="meeting", source_id=mid, locator="1"))], ctx(), stack.adapters)
        assert bundle.items == [] and bundle.dropped == {"over_ceiling": 1}  # ...and revalidation already enforces the new label
        await stack.worker.drain()
        assert (await index.get(f"meeting:{mid}#1")).sensitivity == Privacy.SENSITIVE
        assert (await client.delete(f"/meetings/{mid}")).status_code == 200
        assert [await present(f"meeting:{mid}#{i}") for i in (0, 1)] == [False, False]
        await client.aclose()
        status = await stack.outbox.status(datetime.now(UTC))
        assert status.failed == 0

    run_stack(env, go)
