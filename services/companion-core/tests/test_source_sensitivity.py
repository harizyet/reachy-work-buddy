"""Phase 44A migration 026 (docs/phase-44.md D2, D8, D10): classification and scope on the authoritative records.

In-memory checks always run. The Postgres checks are opt-in (DATABASE_MIGRATION_TEST_URL must be a disposable server; the
backup check also needs DATABASE_MIGRATION_TEST_CONTAINER) and cover the upgrade from 025, the conservative backfill, clients
that know nothing of the new columns, store round trips and recovery from a dump taken before the upgrade."""

import asyncio
import hashlib
import importlib
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.migrations import __main__ as migrations
from companion_core.migrations.__main__ import upgrade
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.embeddings import EMBEDDING_DIM
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.secrets import Keyring
from companion_core.tasks.postgres_store import PostgresTaskStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.database import SCHEMA_REVISION
from shared.models.response import Privacy

NEW_TABLES = ("document_chunks", "notes", "tasks", "reminders", "meetings")


def _embed(texts: list[str]) -> list[list[float]]:
    out = []
    for text in texts:
        vector = [0.0] * EMBEDDING_DIM
        for word in text.lower().split():
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % EMBEDDING_DIM] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        out.append([v / norm for v in vector] if norm else vector)
    return out


# ---- in-memory stores ------------------------------------------------------------------------------------------

def test_new_records_default_to_work_private_and_unscoped() -> None:
    async def run() -> None:
        (chunk,) = await InMemoryDocumentStore(embed_fn=_embed).ingest_document(title="t", content="body", source="s")
        note = await InMemoryPlannerStore().add_note("n", "b")
        reminder = await InMemoryPlannerStore().add_reminder("r", datetime.now(UTC) + timedelta(hours=1))
        task = await InMemoryTaskStore().add_task("t")
        meeting = await InMemoryMeetingStore().create_meeting(
            title="m", audio=b"x", source_filename="a.wav", content_type="audio/wav"
        )
        for record in (chunk, note, reminder, task, meeting):
            assert record.sensitivity == Privacy.WORK_PRIVATE
        for record in (chunk, note, task, meeting):
            assert record.project_scope is None

    asyncio.run(run())


def test_classification_and_scope_are_kept_and_editing_never_changes_them() -> None:
    async def run() -> None:
        docs = InMemoryDocumentStore(embed_fn=_embed)
        chunks = await docs.ingest_document(
            title="t", content="# a\none\n\n# b\ntwo", source="s", sensitivity=Privacy.SENSITIVE, project_scope="alpha"
        )
        assert {(c.sensitivity, c.project_scope) for c in chunks} == {(Privacy.SENSITIVE, "alpha")}
        found = await docs.search("one")
        assert found[0].chunk.sensitivity == Privacy.SENSITIVE

        planner = InMemoryPlannerStore()
        note = await planner.add_note("n", "b", sensitivity=Privacy.PUBLIC, project_scope="beta")
        edited = await planner.update_note(note.id, "n2", "b2")
        assert (edited.sensitivity, edited.project_scope) == (Privacy.PUBLIC, "beta")

        tasks = InMemoryTaskStore()
        task = await tasks.add_task("x", sensitivity=Privacy.SENSITIVE, project_scope="alpha")
        for changed in (
            await tasks.complete_task(task.id), await tasks.reopen_task(task.id), await tasks.update_task_text(task.id, "y"),
        ):
            assert (changed.sensitivity, changed.project_scope) == (Privacy.SENSITIVE, "alpha")

        meeting = await InMemoryMeetingStore().create_meeting(
            title="m", audio=b"x", source_filename="a.wav", content_type="audio/wav", sensitivity=Privacy.SENSITIVE
        )
        assert meeting.sensitivity == Privacy.SENSITIVE

    asyncio.run(run())


def make_client() -> TestClient:
    return TestClient(
        create_app(
            calendar_store=InMemoryCalendarStore(),
            task_store=InMemoryTaskStore(),
            planner_store=InMemoryPlannerStore(),
            meeting_store=InMemoryMeetingStore(),
            run_meeting_worker_task=False,
            memory_store=InMemoryMemoryStore(),
            rag_store=InMemoryDocumentStore(embed_fn=_embed),
            email_store=InMemoryEmailStore(),
            confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(),
            llm_usage_store=InMemoryLLMUsageStore(),
            persona_store=InMemoryPersonaStore(),
            search_settings_store=InMemorySearchSettingsStore(),
            run_email_dispatch_task=False,
        )
    )


def test_api_accepts_the_new_fields_and_old_clients_still_work() -> None:
    client = make_client()
    # A client that knows nothing of the new fields gets the conservative defaults.
    assert client.post("/tasks", json={"text": "old client"}).json()["sensitivity"] == "work-private"
    assert client.post("/notes", json={"title": "old", "body": ""}).json()["project_scope"] is None
    reminder = client.post("/reminders", json={"text": "r", "due_at": "2030-01-01T00:00:00+00:00"}).json()
    assert reminder["sensitivity"] == "work-private"
    classified = client.post("/tasks", json={"text": "new", "sensitivity": "sensitive", "project_scope": "alpha"}).json()
    assert (classified["sensitivity"], classified["project_scope"]) == ("sensitive", "alpha")
    assert client.post("/tasks", json={"text": "bad", "sensitivity": "secret"}).status_code == 422
    document = client.post("/documents", json={"title": "d", "content": "hello", "sensitivity": "public"})
    assert document.status_code == 200 and document.json()[0]["sensitivity"] == "public"
    assert client.post("/documents", json={"title": "d", "content": "hello"}).json()[0]["sensitivity"] == "work-private"
    upload = client.post(
        "/meetings", data={"title": "m", "sensitivity": "sensitive"}, files={"audio": ("a.wav", b"RIFFxxxx", "audio/wav")}
    )
    assert upload.status_code == 200 and upload.json()["sensitivity"] == "sensitive"
    plain = client.post("/meetings", data={"title": "m2"}, files={"audio": ("a.wav", b"RIFFxxxx", "audio/wav")})
    assert plain.json()["sensitivity"] == "work-private"
    # Editing never reclassifies.
    note = client.post("/notes", json={"title": "n", "sensitivity": "public", "project_scope": "beta"}).json()
    assert client.put(f"/notes/{note['id']}", json={"title": "n2"}).json()["sensitivity"] == "public"


# ---- Postgres ---------------------------------------------------------------------------------------------------

postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres"
)
KEYS = Keyring("one", {"one": b"\x01" * 32})


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
    """Bring a fresh database to `revision` only, so a previous schema can be seeded and then upgraded for real."""
    from sqlalchemy import create_engine

    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), hide_parameters=True)
    try:
        with engine.begin() as conn:
            config = Config()
            config.set_main_option("script_location", str(Path(migrations.__file__).parent))
            config.attributes.update(connection=conn, keyring=KEYS, adopt_legacy=False)
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def seed_025(dsn: str) -> None:
    upgrade_to(dsn, "025_meeting_description")
    zeros = "[" + ",".join(["0"] * EMBEDDING_DIM) + "]"
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO document_chunks (id, document_id, document_title, section, content, source, chunk_index, "
            f"created_at, embedding) VALUES ('c1','d1','Doc',NULL,'old chunk','api',0,now(),'{zeros}')"
        )
        conn.execute("INSERT INTO notes VALUES ('n1','old note','body',now(),now())")
        conn.execute("INSERT INTO tasks VALUES ('t1','old task','open',now(),NULL)")
        conn.execute(
            "INSERT INTO reminders (id, text, due_at, status, created_at) VALUES ('r1','old reminder',now(),'pending',now())"
        )
        conn.execute(
            "INSERT INTO memories VALUES ('m1','working','old memory','conversation','alpha',1.0,'sensitive',now(),NULL,NULL,NULL)"
        )
        conn.execute(
            "INSERT INTO meetings (id, title, project_scope, source_filename, content_type, audio_path, status) "
            "VALUES ('mt1','old meeting','alpha','a.wav','audio/wav','mt1/a.wav','complete')"
        )


@postgres
def test_upgrade_from_025_backfills_conservatively_and_infers_nothing(database):
    seed_025(database)
    upgrade(database, KEYS)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (SCHEMA_REVISION,)
        for table in NEW_TABLES:
            assert conn.execute(f"SELECT DISTINCT sensitivity FROM {table}").fetchall() == [("work-private",)], table
        for table in ("document_chunks", "notes", "tasks"):
            assert conn.execute(f"SELECT project_scope FROM {table}").fetchall() == [(None,)], table
        # Pre-existing values are preserved, not rewritten: the meeting keeps the scope the owner gave it, the memory keeps
        # its own classification (memories already had both columns and are untouched by 026).
        assert conn.execute("SELECT project_scope, title FROM meetings").fetchone() == ("alpha", "old meeting")
        assert conn.execute("SELECT sensitivity, project_scope FROM memories").fetchone() == ("sensitive", "alpha")
        assert conn.execute("SELECT text FROM tasks").fetchone() == ("old task",)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE tasks SET sensitivity = 'secret'")


@postgres
def test_repeat_upgrade_is_a_no_op_and_downgrade_is_refused(database):
    seed_025(database)
    upgrade(database, KEYS)
    upgrade(database, KEYS)
    module = importlib.import_module("companion_core.migrations.versions.026_source_sensitivity")
    with pytest.raises(RuntimeError, match="Restore a tested backup"):
        module.downgrade()


@postgres
def test_sql_that_does_not_know_the_new_columns_still_works(database):
    """Existing explicit-column inserts (an old client, a script) get the conservative defaults."""
    upgrade(database, KEYS)
    with psycopg.connect(database) as conn:
        conn.execute("INSERT INTO tasks (id, text, status, created_at, completed_at) VALUES ('x','t','open',now(),NULL)")
        conn.execute("INSERT INTO notes (id, title, body, created_at, updated_at) VALUES ('y','t','b',now(),now())")
        assert conn.execute("SELECT sensitivity, project_scope FROM tasks").fetchone() == ("work-private", None)
        assert conn.execute("SELECT sensitivity, project_scope FROM notes").fetchone() == ("work-private", None)


@postgres
def test_stores_round_trip_classification_and_scope_and_preserve_it_on_edit(database, tmp_path):
    seed_025(database)
    upgrade(database, KEYS)

    async def run() -> None:
        docs = await PostgresDocumentStore.connect(database, embed_fn=_embed)
        chunks = await docs.ingest_document(
            title="Plan", content="alpha beta gamma", source="api", sensitivity=Privacy.SENSITIVE, project_scope="alpha"
        )
        (hit,) = [r for r in await docs.search("alpha beta gamma", top_k=5) if r.chunk.id == chunks[0].id]
        assert (hit.chunk.sensitivity, hit.chunk.project_scope) == (Privacy.SENSITIVE, "alpha")
        old = next(r for r in await docs.search("old chunk", top_k=5) if r.chunk.id == "c1")
        assert (old.chunk.sensitivity, old.chunk.project_scope) == (Privacy.WORK_PRIVATE, None)
        await docs.close()

        planner = await PostgresPlannerStore.connect(database)
        note = await planner.add_note("n", "b", sensitivity=Privacy.PUBLIC, project_scope="beta")
        edited = await planner.update_note(note.id, "n2", "b2")
        assert (edited.sensitivity, edited.project_scope) == (Privacy.PUBLIC, "beta")
        reminder = await planner.add_reminder("r", datetime.now(UTC) + timedelta(hours=1), sensitivity=Privacy.SENSITIVE)
        assert (await planner.complete_reminder(reminder.id)).sensitivity == Privacy.SENSITIVE
        listed = {n.id: n for n in await planner.list_notes()}
        assert listed["n1"].sensitivity == Privacy.WORK_PRIVATE and listed["n1"].project_scope is None
        await planner.close()

        tasks = await PostgresTaskStore.connect(database)
        task = await tasks.add_task("x", sensitivity=Privacy.SENSITIVE, project_scope="alpha")
        for changed in (
            await tasks.complete_task(task.id), await tasks.reopen_task(task.id), await tasks.update_task_text(task.id, "y"),
        ):
            assert (changed.sensitivity, changed.project_scope) == (Privacy.SENSITIVE, "alpha")
        assert {t.id: t.sensitivity for t in await tasks.search_tasks("old")} == {"t1": Privacy.WORK_PRIVATE}
        await tasks.close()

        meetings = await PostgresMeetingStore.connect(database, audio_dir=tmp_path)
        meeting = await meetings.create_meeting(
            title="m", audio=b"x", source_filename="a.wav", content_type="audio/wav", sensitivity=Privacy.SENSITIVE
        )
        fetched = await meetings.get_meeting(meeting.id)
        assert fetched.sensitivity == Privacy.SENSITIVE
        renamed = await meetings.set_title(meeting.id, title="renamed", description=None, source="owner")
        assert renamed.sensitivity == Privacy.SENSITIVE
        assert (await meetings.get_meeting("mt1")).sensitivity == Privacy.WORK_PRIVATE
        assert (await meetings.get_meeting("mt1")).project_scope == "alpha"
        await meetings.close()

    asyncio.run(run())


@postgres
def test_recovery_from_a_dump_taken_before_the_upgrade(database):
    container = os.environ.get("DATABASE_MIGRATION_TEST_CONTAINER")
    if not container:
        pytest.skip("requires the disposable Postgres container for pg_dump/pg_restore")
    name = psycopg.conninfo.conninfo_to_dict(database)["dbname"]
    seed_025(database)
    backup = subprocess.run(
        ["docker", "exec", container, "pg_dump", "-U", "fixture", "-Fc", name], check=True, capture_output=True
    ).stdout
    upgrade(database, KEYS)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (SCHEMA_REVISION,)
    # Since revision 027 the derived knowledge tables depend on the vector type, which a --clean restore tries to drop. The documented
    # recovery therefore removes them first (deploy/homelab/rollback-027.sql); they are rebuilt from the stores afterwards.
    with psycopg.connect(database) as conn:
        conn.execute((Path(__file__).parents[3] / "deploy" / "homelab" / "rollback-027.sql").read_text())
    subprocess.run(
        ["docker", "exec", "-i", container, "pg_restore", "-U", "fixture", "--clean", "--if-exists", "--no-owner", "-d", name],
        input=backup, check=True, capture_output=True,
    )
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("025_meeting_description",)
        columns = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'tasks'").fetchall()}
        assert "sensitivity" not in columns
        assert conn.execute("SELECT text FROM tasks").fetchone() == ("old task",)
    upgrade(database, KEYS)  # the same upgrade succeeds again from the restored state
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT sensitivity FROM tasks").fetchone() == ("work-private",)


@postgres
def test_ossie_catalogue_columns_exist_in_the_migrated_database(database):
    """The structural export is built from the store models; this ties it to the real tables so it cannot describe a column
    that is not there."""
    from companion_core.semantic.ossie import mapping

    upgrade(database, KEYS)
    with psycopg.connect(database) as conn:
        for spec in mapping.DATASETS:
            actual = {
                r[0]
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s",
                    (spec.table,),
                ).fetchall()
            }
            assert set(mapping.column_names(spec)) <= actual, (spec.name, set(mapping.column_names(spec)) - actual)
