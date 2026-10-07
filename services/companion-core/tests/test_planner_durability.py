"""Opt-in real Postgres checks for the planner tables and stores.
DATABASE_MIGRATION_TEST_URL must point at a disposable server."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from companion_core.migrations.__main__ import upgrade
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.secrets import Keyring
from companion_core.tasks.postgres_store import PostgresTaskStore

from shared.models.receipt import ActionReceipt

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_MIGRATION_TEST_URL"),
    reason="requires explicitly disposable Postgres",
)


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
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def test_notes_reminders_and_tasks_persist_across_reconnect(database):
    now = datetime.now(UTC)

    async def write():
        store = await PostgresPlannerStore.connect(database)
        tasks = await PostgresTaskStore.connect(database)
        try:
            note = await store.add_note("100%_sure", "body")
            await store.add_note("other", "text")
            assert [n.id for n in await store.list_notes("100%_")] == [note.id]
            assert [n.id for n in await store.list_notes("%")] == [note.id]
            past = await store.add_reminder("past", now - timedelta(minutes=1))
            await store.add_reminder("later", now + timedelta(hours=1))
            task = await tasks.add_task("t")
            await tasks.complete_task(task.id)
            assert (await tasks.reopen_task(task.id)).completed_at is None
            assert (await tasks.update_task_text(task.id, "t2")).text == "t2"
            return note.id, past.id
        finally:
            await store.close()
            await tasks.close()

    note_id, past_id = asyncio.run(write())

    async def read():
        store = await PostgresPlannerStore.connect(database)
        try:
            assert (await store.update_note(note_id, "renamed", "b")).title == "renamed"
            assert [r.id for r in await store.claim_due(now)] == [past_id]
            assert await store.claim_due(now) == []
            assert (await store.complete_reminder(past_id)).status.value == "done"
            assert len(await store.list_reminders()) == 2
            assert await store.delete_note(note_id) is True
            assert await store.delete_note(note_id) is False
            assert await store.delete_reminder(past_id) is True
        finally:
            await store.close()

    asyncio.run(read())


def test_alarms_and_stations_persist_and_claim_once(database):
    now = datetime.now(UTC)

    async def write():
        store = await PostgresPlannerStore.connect(database)
        try:
            station = await store.add_station("Zed FM", "s2")
            assert (await store.add_station("renamed", "s2")).id == station.id
            due = await store.add_alarm("wake", now - timedelta(minutes=1), reminder_id="r1", station_id=station.id, volume=250)
            skipped = await store.add_alarm("skip", now - timedelta(minutes=2))
            await store.add_alarm("later", now + timedelta(hours=1))
            assert (await store.cancel_alarm(skipped.id)).status == "cancelled"
            return station.id, due.id
        finally:
            await store.close()

    station_id, due_id = asyncio.run(write())

    async def read():
        store = await PostgresPlannerStore.connect(database)
        try:
            claimed = await store.claim_due_alarms(now)
            assert [a.id for a in claimed] == [due_id]
            assert claimed[0].status == "fired" and claimed[0].station_id == station_id
            assert claimed[0].volume == 250
            assert await store.claim_due_alarms(now) == []
            assert (await store.record_alarm_delivery(due_id, "played")).delivery == "played"
            assert [a.label for a in await store.list_alarms()] == ["skip", "wake", "later"]
            assert await store.delete_station(station_id) is True
            assert await store.delete_station(station_id) is False
            assert (await store.cancel_alarm(due_id)).status == "cancelled"  # a finished alarm can be removed
        finally:
            await store.close()

    asyncio.run(read())


def test_alarm_repeat_switch_update_and_rearm_persist(database):
    now = datetime.now(UTC)

    async def run():
        store = await PostgresPlannerStore.connect(database)
        try:
            daily = await store.add_alarm("daily", now - timedelta(minutes=1), repeat=[4, 0, 0])
            assert daily.repeat == [0, 4] and daily.enabled is True
            off = await store.add_alarm("off", now - timedelta(minutes=1))
            assert (await store.update_alarm(off.id, {"enabled": False})).enabled is False
            claimed = await store.claim_due_alarms(now)
            assert [a.id for a in claimed] == [daily.id]  # the disabled one never rings
            assert (await store.rearm_alarm(daily.id, now + timedelta(days=1))).status == "scheduled"
            assert (await store.rearm_alarm(off.id, now + timedelta(days=1))).status == "scheduled"  # not fired, not repeating: unchanged
            edited = await store.update_alarm(daily.id, {"label": "Run", "volume": 120, "repeat": [1], "station_id": None})
            assert (edited.label, edited.volume, edited.repeat) == ("Run", 120, [1])
            back = await store.update_alarm(off.id, {"enabled": True, "due_at": now - timedelta(seconds=5)})
            assert back.enabled and back.status == "scheduled"
            assert [a.id for a in await store.claim_due_alarms(now)] == [off.id]
            reread = {a.id: a for a in await store.list_alarms()}
            assert reread[daily.id].repeat == [1] and reread[daily.id].label == "Run"
            assert await store.update_alarm("nope", {"enabled": True}) is None
        finally:
            await store.close()

    asyncio.run(run())


def test_receipts_persist_and_claim_once(database):
    now = datetime.now(UTC)

    async def run():
        store = await PostgresPlannerStore.connect(database)
        try:
            await store.add_receipt(ActionReceipt(action_type="task.created", source_channel="web", object_type="task",
                                                  fields={"Task": "t"}, notify=True, at=now - timedelta(seconds=5)))
            await store.add_receipt(ActionReceipt(action_type="alarm.created", source_channel="web", object_type="alarm"))
        finally:
            await store.close()
        store = await PostgresPlannerStore.connect(database)
        try:
            listed = await store.list_receipts()
            assert [r.action_type for r in listed] == ["alarm.created", "task.created"]
            assert listed[1].fields == {"Task": "t"}
            assert [r.action_type for r in await store.claim_receipts_to_notify(now)] == ["task.created"]
            assert await store.claim_receipts_to_notify(now) == []
        finally:
            await store.close()

    asyncio.run(run())
