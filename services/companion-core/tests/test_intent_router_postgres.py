"""Hybrid intent routing over the real PostgreSQL stores (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector). The router's execution step reads the real task,
reminder, note, memory and meeting tables under the turn's access context; the model's only role (a JSON decision) is supplied directly. Synthetic data only."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from companion_core import intent_router
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.migrations.__main__ import upgrade
from companion_core.notepad_processing import inquiry
from companion_core.notepad_processing.postgres_store import PostgresNotepadStore
from companion_core.notepad_processing.service import NotepadService
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.secrets import Keyring
from companion_core.semantic.access import access_for_owner
from companion_core.tasks.postgres_store import PostgresTaskStore

from shared.models.memory import MemoryType
from shared.models.response import Privacy

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
KEYS = Keyring("one", {"one": b"\x01" * 32})
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)  # a Sunday: next week starts tomorrow
PRIVATE = access_for_owner("t", channel_private=True)
SPEAKER = access_for_owner("t", channel_private=False)


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


def decision(operation, **kwargs):
    return intent_router.Decision(operation=operation, confidence=0.95, **kwargs)


def test_every_routed_read_runs_against_the_real_tables_and_changes_nothing(dsn, tmp_path):
    async def go():
        tasks, planner, memory, store = await PostgresTaskStore.connect(dsn), await PostgresPlannerStore.connect(dsn), await PostgresMemoryStore.connect(dsn), await PostgresNotepadStore.connect(dsn)
        meetings = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        try:
            async def zone():
                return "UTC"

            service = NotepadService(store, planner, tasks, zone, provider=None, meetings=meetings, clock=lambda: NOW)
            await tasks.add_task("Water the plants")
            await planner.add_note("My Task for next week", "Draft the quarterly summary.")
            await planner.add_note("Infra planning", "Move the GitLab runners before month end.")
            await planner.add_note("Medical", "The diagnosis is private.", sensitivity=Privacy.SENSITIVE)
            await planner.add_reminder("Pay the invoice", NOW + timedelta(days=2))
            await planner.add_reminder("Far away", NOW + timedelta(days=30))
            await memory.add_memory(content="The Google on-prem contact is Priya Raman", source="test", type=MemoryType.PROFILE, sensitivity=Privacy.WORK_PRIVATE)
            common = {"tasks": tasks, "planner": planner, "memory": memory, "meetings": meetings, "notepad_service": service, "timezone": "UTC", "now": NOW}

            routed = await intent_router.execute(decision("tasks.list"), "tasks outstanding for me next week?", access=PRIVATE, **common)
            assert "Water the plants" in routed.reply and "none can be placed in next week" in routed.reply and "undated" in routed.reply and routed.handler == "router.tasks.list"
            routed = await intent_router.execute(decision("reminders.list"), "reminders pending for me next week?", access=PRIVATE, **common)
            assert "Pay the invoice" in routed.reply and "Far away" not in routed.reply
            routed = await intent_router.execute(decision("notes.list"), "notes?", access=PRIVATE, **common)
            assert "Infra planning" in routed.reply and "Medical" not in routed.reply
            routed = await intent_router.execute(decision("records.find", kind="note", query="GitLab"), "what did I write in my note about GitLab?", access=PRIVATE, **common)
            assert "Move the GitLab runners before month end." in routed.reply
            routed = await intent_router.execute(decision("records.find", kind="note", query="diagnosis"), "what did I write in my note about the diagnosis?", access=PRIVATE, **common)
            assert "diagnosis is private" not in routed.reply and routed.reply.startswith("I couldn't find")
            routed = await intent_router.execute(decision("memory.recall", query="Google on-prem contact"), "who is the Google on-prem contact?", access=PRIVATE, **common)
            assert "Priya Raman" in routed.reply
            for operation, query in [("tasks.list", None), ("reminders.list", None), ("notes.list", None), ("records.find", "GitLab")]:
                routed = await intent_router.execute(decision(operation, query=query), "anything for next week?", access=SPEAKER, **common)
                assert routed.reply == inquiry.RESTRICTED, operation  # a shared speaker is read nothing

            routed = await intent_router.execute(decision("tasks.list"), "tasks outstanding for me on friday?", access=PRIVATE, **common)
            assert routed.reply == intent_router.SCOPE_LIMITS["unsupported"]
            assert [t.text for t in await tasks.list_tasks()] == ["Water the plants"] and len(await planner.list_notes()) == 3 and len(await planner.list_reminders()) == 2
        finally:
            for closer in (tasks, planner, memory, store, meetings):
                await closer.close()

    asyncio.run(go())
