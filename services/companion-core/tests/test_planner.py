"""Planner store and /notes, /reminders, /tasks edit routes (in-process)."""

import asyncio
from datetime import UTC, datetime, timedelta

from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
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

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def test_notes_search_update_delete() -> None:
    async def run() -> None:
        store = InMemoryPlannerStore()
        a = await store.add_note("Groceries", "milk and eggs")
        await store.add_note("Ideas", "robot hat")
        assert [n.title for n in await store.list_notes("EGGS")] == ["Groceries"]
        updated = await store.update_note(a.id, "Shopping", "bread")
        assert updated.title == "Shopping" and updated.updated_at >= a.updated_at
        assert await store.update_note("nope", "x", "y") is None
        assert await store.delete_note(a.id) is True
        assert await store.delete_note(a.id) is False

    asyncio.run(run())


def test_claim_due_returns_each_pending_reminder_once() -> None:
    async def run() -> None:
        store = InMemoryPlannerStore()
        past = await store.add_reminder("past", NOW - timedelta(minutes=1))
        await store.add_reminder("future", NOW + timedelta(hours=1))
        done = await store.add_reminder("done", NOW - timedelta(minutes=5))
        await store.complete_reminder(done.id)
        assert [r.id for r in await store.claim_due(NOW)] == [past.id]
        assert await store.claim_due(NOW) == []
        assert len(await store.list_reminders()) == 3

    asyncio.run(run())


def test_task_reopen_edit_delete() -> None:
    async def run() -> None:
        store = InMemoryTaskStore()
        task = await store.add_task("a")
        await store.complete_task(task.id)
        assert (await store.reopen_task(task.id)).completed_at is None
        assert (await store.update_task_text(task.id, "b")).text == "b"
        assert await store.delete_task(task.id) is True
        assert await store.delete_task(task.id) is False
        assert await store.reopen_task(task.id) is None

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
            rag_store=InMemoryDocumentStore(),
            email_store=InMemoryEmailStore(),
            confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(),
            llm_usage_store=InMemoryLLMUsageStore(),
            persona_store=InMemoryPersonaStore(),
            search_settings_store=InMemorySearchSettingsStore(),
            run_email_dispatch_task=False,
        )
    )


def test_routes_round_trip() -> None:
    client = make_client()
    task = client.post("/tasks", json={"text": "a"}).json()
    assert client.put(f"/tasks/{task['id']}", json={"text": "b"}).json()["text"] == "b"
    client.post(f"/tasks/{task['id']}/complete")
    assert client.post(f"/tasks/{task['id']}/reopen").json()["status"] == "open"
    assert client.delete(f"/tasks/{task['id']}").json() == {"deleted": True}
    assert client.delete(f"/tasks/{task['id']}").status_code == 404

    note = client.post("/notes", json={"title": "T", "body": "hello"}).json()
    assert client.get("/notes", params={"q": "hell"}).json()[0]["id"] == note["id"]
    assert (
        client.put(f"/notes/{note['id']}", json={"title": "T2"}).json()["title"] == "T2"
    )
    assert client.post("/notes", json={"title": ""}).status_code == 422
    assert client.delete("/notes/missing").status_code == 404

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    reminder = client.post("/reminders", json={"text": "r", "due_at": past}).json()
    assert (
        client.post(
            "/reminders", json={"text": "r", "due_at": "2026-10-04T12:00:00"}
        ).status_code
        == 422
    )
    assert [r["id"] for r in client.get("/reminders/due").json()] == [reminder["id"]]
    assert client.get("/reminders/due").json() == []
    assert (
        client.post(f"/reminders/{reminder['id']}/complete").json()["status"] == "done"
    )
    assert client.delete(f"/reminders/{reminder['id']}").json() == {"deleted": True}


def test_remind_me_with_a_time_creates_a_todo_and_a_reminder() -> None:
    client = make_client()
    turn = {"session_id": "s", "conversation_id": "c", "channel": "telegram"}
    reply = client.post("/conversation", json={**turn, "text": "remind me to email brian later at 4pm"}).json()["reply"]
    assert "I'll also remind you" in reply
    assert [t["text"] for t in client.get("/tasks").json()] == ["email brian later at 4pm"]
    assert [r["text"] for r in client.get("/reminders").json()] == ["email brian"]

    reply = client.post("/conversation", json={**turn, "text": "remind me to buy milk"}).json()["reply"]
    assert "also remind" not in reply
    assert len(client.get("/reminders").json()) == 1
