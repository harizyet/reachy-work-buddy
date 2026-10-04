"""Phase 29.27: coding-agent records survive a service restart. Opt-in real
Postgres checks; DATABASE_MIGRATION_TEST_URL must point at a disposable
server (docs/development.md). Lives in companion-core's tests because the
schema is owned by its single Alembic history (ADR 0020) and the claim-once
notification ledger is core's. Sibling imports are test-only.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import psycopg
import pytest
from coding_agent_service.app import create_app as create_coding_agent_app
from coding_agent_service.postgres_store import PostgresCodingAgentStore
from coding_agent_service.runtime import SimulatedContainerRuntime
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.coding_agent_notifications import (
    PostgresCodingAgentNotificationStore,
)
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.migrations.__main__ import upgrade
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.secrets import Keyring
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.database import SCHEMA_REVISION
from shared.models.coding_agent import (
    CodingAgentEvent,
    CodingAgentEventType,
    CodingAgentSession,
    CodingAgentStatus,
    CodingProject,
    UsageDimension,
    UsageSnapshot,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_MIGRATION_TEST_URL"),
    reason="requires explicitly disposable Postgres",
)

TOKEN = "durability-token"
HEADERS = {"X-Reachy-Coding-Agent-Service-Token": TOKEN}


@pytest.fixture
def database():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    dsn = psycopg.conninfo.make_conninfo(root, dbname=name)
    upgrade(dsn, Keyring("one", {"one": os.urandom(32)}))
    try:
        yield dsn
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                psycopg.sql.Identifier(name)))


async def _with_store(dsn, fn):
    store = PostgresCodingAgentStore(dsn)
    await store.open()
    try:
        return await fn(store)
    finally:
        await store.close()


def test_migration_creates_the_coding_agent_tables(database):
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (SCHEMA_REVISION,)
        tables = {row[0] for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
            "AND table_name LIKE 'coding_agent_%'"
        )}
    assert tables == {
        "coding_agent_projects", "coding_agent_sessions", "coding_agent_events",
        "coding_agent_usage_snapshots", "coding_agent_notifications",
    }


def test_store_records_survive_closing_and_reopening(database):
    ids = {}

    async def write(store):
        project = await store.add_project(CodingProject(name="P", repository_path="/p", provider="simulated"))
        session = CodingAgentSession(
            project_id=project.id, provider="simulated", task_summary="work", owner_user_id="owner-1",
        )
        await store.add_session(session)
        session.status = CodingAgentStatus.COMPLETED
        session.last_event = "done"
        await store.update_session(session)
        for index in range(3):
            await store.add_event(CodingAgentEvent(
                session_id=session.id, type=CodingAgentEventType.AGENT_STILL_RUNNING, summary=f"event {index}",
            ))
        await store.add_usage_snapshot(UsageSnapshot(
            session_id=session.id, provider="simulated",
            dimensions=[UsageDimension(name="input_tokens", value=7, unit="tokens")],
        ))
        ids.update(project=project.id, session=session.id)

    asyncio.run(_with_store(database, write))

    async def read(store):
        assert [p.id for p in await store.list_projects()] == [ids["project"]]
        session = await store.get_session(ids["session"])
        assert session.status == CodingAgentStatus.COMPLETED and session.last_event == "done"
        assert [s.id for s in await store.list_sessions()] == [ids["session"]]
        assert [e.summary for e in await store.list_events(ids["session"])] == ["event 0", "event 1", "event 2"]
        latest = await store.latest_usage_snapshot(ids["session"])
        assert latest.dimensions[0].value == 7
        assert len(await store.recent_usage_snapshots("simulated", 10)) == 1
        assert await store.get_session("missing") is None

    asyncio.run(_with_store(database, read))


def test_store_refuses_an_unmigrated_database():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    try:
        dsn = psycopg.conninfo.make_conninfo(root, dbname=name)
        with pytest.raises(RuntimeError, match="unversioned"):
            asyncio.run(_with_store(dsn, lambda store: asyncio.sleep(0)))
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                psycopg.sql.Identifier(name)))


def test_service_restart_keeps_sessions_and_reconciles_vanished_containers(database):
    runtime = SimulatedContainerRuntime()

    def build():
        return create_coding_agent_app(
            store=PostgresCodingAgentStore(database), service_token=TOKEN, container_runtime=runtime,
        )

    with TestClient(build()) as service:
        project = service.post("/projects", headers=HEADERS, json={
            "name": "P", "repository_path": "/p", "provider": "simulated",
        }).json()
        done = service.post("/sessions", headers=HEADERS, json={
            "project_id": project["id"], "task_summary": "Finished task", "owner_user_id": "owner-1",
        }).json()
        waiting = service.post("/sessions", headers=HEADERS, json={
            "project_id": project["id"], "task_summary": "ask: pick one", "owner_user_id": "owner-1",
        }).json()
        claude_project = service.post("/projects", headers=HEADERS, json={
            "name": "C", "repository_path": "/c", "provider": "claude-code",
        }).json()

    async def seed_running_claude_session(store):
        session = CodingAgentSession(
            project_id=claude_project["id"], provider="claude-code", status=CodingAgentStatus.RUNNING,
            task_summary="was running", owner_user_id="owner-1", container_id="gone-container",
        )
        await store.add_session(session)
        return session.id

    claude_session_id = asyncio.run(_with_store(database, seed_running_claude_session))

    # "Restart": a brand-new app, store and pool over the same database.
    with TestClient(build()) as service:
        sessions = {s["id"]: s for s in service.get("/sessions", headers=HEADERS).json()}
        assert sessions[done["id"]]["status"] == "completed"
        assert sessions[waiting["id"]]["status"] == "waiting_for_input"
        assert sessions[claude_session_id]["status"] == "lost"
        assert "no longer exists" in sessions[claude_session_id]["last_event"]
        assert service.get(f"/sessions/{done['id']}/events", headers=HEADERS).json()


def test_final_usage_and_allowance_survive_restart(database):
    resets_at = datetime.now(UTC) + timedelta(hours=3)

    async def write(store):
        project = await store.add_project(CodingProject(name="P", repository_path="/p", provider="simulated"))
        session = CodingAgentSession(
            project_id=project.id, provider="simulated", task_summary="x", owner_user_id="owner-1",
        )
        await store.add_session(session)
        await store.add_usage_snapshot(UsageSnapshot(
            session_id=session.id, provider="simulated",
            dimensions=[UsageDimension(name="five_hour_window", value=64.0, unit="%", resets_at=resets_at)],
        ))

    asyncio.run(_with_store(database, write))
    app = create_coding_agent_app(store=PostgresCodingAgentStore(database), service_token=TOKEN)
    with TestClient(app) as service:
        body = service.get("/providers/simulated/allowance", headers=HEADERS).json()
    assert [(w["name"], w["value"]) for w in body["windows"]] == [("five_hour_window", 64.0)]


def test_notification_claims_are_atomic_and_survive_reconnect(database):
    async def go():
        first = await PostgresCodingAgentNotificationStore.connect(database)
        second = await PostgresCodingAgentNotificationStore.connect(database)
        try:
            results = await asyncio.gather(*(store.claim("s1") for store in (first, second) * 4))
            assert results.count(True) == 1
        finally:
            await first.close()
            await second.close()
        reopened = await PostgresCodingAgentNotificationStore.connect(database)
        try:
            assert await reopened.claim("s1") is False
            assert await reopened.claim("s2") is True
        finally:
            await reopened.close()

    asyncio.run(go())


def test_core_restart_does_not_renotify_finished_sessions(database):
    coding_app = create_coding_agent_app(store=PostgresCodingAgentStore(database), service_token=TOKEN)

    def core():
        def respond(request):
            raise AssertionError("no model call expected")

        return create_app(
            calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
            meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
            memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(),
            email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
            persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
            run_email_dispatch_task=False, llm_transport=httpx.MockTransport(respond),
            coding_agent_base_url="http://coding-agent-service",
            coding_agent_transport=httpx.ASGITransport(app=coding_app),
            coding_agent_service_token=TOKEN, database_url=database,
        )

    with TestClient(coding_app) as service:
        project = service.post("/projects", headers=HEADERS, json={
            "name": "P", "repository_path": "/p", "provider": "simulated",
        }).json()
        service.post("/sessions", headers=HEADERS, json={
            "project_id": project["id"], "task_summary": "Finished task", "owner_user_id": "owner-1",
        })
        with TestClient(core()) as client:
            assert len(client.get("/coding-agents/completions/due").json()) == 1
        with TestClient(core()) as client:
            assert client.get("/coding-agents/completions/due").json() == []
