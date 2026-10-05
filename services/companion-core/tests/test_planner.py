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


def test_alarm_store_claims_each_scheduled_alarm_once_and_skips_cancelled() -> None:
    async def run() -> None:
        store = InMemoryPlannerStore()
        due = await store.add_alarm("wake", NOW - timedelta(minutes=1), reminder_id="r1", station_id="s1")
        cancelled = await store.add_alarm("skip", NOW - timedelta(minutes=2))
        await store.add_alarm("later", NOW + timedelta(hours=1))
        assert (await store.cancel_alarm(cancelled.id)).status == "cancelled"
        assert await store.cancel_alarm("nope") is None
        claimed = await store.claim_due_alarms(NOW)
        assert [a.id for a in claimed] == [due.id]
        assert claimed[0].status == "fired" and claimed[0].fired_at == NOW
        assert await store.claim_due_alarms(NOW) == []
        assert (await store.cancel_alarm(due.id)).status == "fired"
        assert (await store.record_alarm_delivery(due.id, "telegram: privacy mode")).delivery == "telegram: privacy mode"
        assert [a.label for a in await store.list_alarms()] == ["skip", "wake", "later"]

    asyncio.run(run())


def test_alarm_routes_create_list_claim_record_and_cancel() -> None:
    client = make_client()
    soon = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert client.post("/alarms", json={"label": "x", "due_at": "2026-10-05T14:00:00"}).status_code == 422
    assert client.post("/alarms", json={"label": "", "due_at": soon}).status_code == 422
    alarm = client.post("/alarms", json={"label": " cake ", "due_at": soon, "reminder_id": "r1"}).json()
    assert alarm["label"] == "cake" and alarm["status"] == "scheduled" and alarm["reminder_id"] == "r1"
    assert [a["id"] for a in client.get("/alarms").json()] == [alarm["id"]]
    assert client.get("/alarms/due").json() == []
    past = client.post("/alarms", json={"label": "now", "due_at": "2026-01-01T00:00:00+00:00"}).json()
    assert [a["id"] for a in client.get("/alarms/due").json()] == [past["id"]]
    assert client.get("/alarms/due").json() == []
    recorded = client.post(f"/alarms/{past['id']}/delivery", json={"delivery": "telegram"}).json()
    assert recorded["delivery"] == "telegram"
    assert client.post("/alarms/nope/delivery", json={"delivery": "x"}).status_code == 404
    assert client.delete(f"/alarms/{alarm['id']}").json()["status"] == "cancelled"
    assert client.delete("/alarms/nope").status_code == 404


def test_station_routes_save_once_per_guide_id_and_list_by_name() -> None:
    client = make_client()
    assert client.post("/stations", json={"name": "x", "guide_id": "bad id"}).status_code == 422
    assert client.post("/stations", json={"name": "x", "guide_id": "http://evil"}).status_code == 422
    b = client.post("/stations", json={"name": " Zed FM ", "guide_id": "s2"}).json()
    a = client.post("/stations", json={"name": "Alpha", "guide_id": "s1"}).json()
    again = client.post("/stations", json={"name": "Other name", "guide_id": "s2"}).json()
    assert again["id"] == b["id"] and b["name"] == "Zed FM"
    assert [s["name"] for s in client.get("/stations").json()] == ["Alpha", "Zed FM"]
    assert client.delete(f"/stations/{a['id']}").json() == {"deleted": True}
    assert client.delete(f"/stations/{a['id']}").status_code == 404


TURN = {"session_id": "s", "conversation_id": "c", "channel": "telegram"}


def say(client: TestClient, text: str, **extra) -> str:
    return client.post("/conversation", json={**TURN, **extra, "text": text}).json()["reply"]


def test_reminder_with_a_day_offers_an_alarm_and_a_time_reply_creates_it() -> None:
    client = make_client()
    reply = say(client, "Remind me to get a cake for joshua's birthday on thursday")
    assert "Would you like an alarm set for Thursday" in reply
    [reminder] = client.get("/reminders").json()
    assert reminder["text"] == "get a cake for joshua's birthday"
    assert "What time" in say(client, "yes sure")
    reply = say(client, "maybe 2pm?")
    assert reply.startswith("Alright, an alarm is set for 2:00 PM")
    [alarm] = client.get("/alarms").json()
    assert alarm["reminder_id"] == reminder["id"] and alarm["due_at"].startswith(reminder["due_at"][:10])
    assert "14:00:00" in alarm["due_at"] or "T14:00" in alarm["due_at"]
    assert say(client, "yes 3pm") != reply and len(client.get("/alarms").json()) == 1


def test_a_timed_reminder_offer_accepts_a_bare_yes_at_the_reminder_time() -> None:
    client = make_client()
    assert "alarm set for that time too" in say(client, "remind me to call the vet tomorrow at 3pm")
    assert say(client, "yes please").startswith("Alright, an alarm is set for 3:00 PM tomorrow")
    [alarm] = client.get("/alarms").json()
    [reminder] = client.get("/reminders").json()
    assert alarm["due_at"] == reminder["due_at"]


def test_declining_or_changing_the_subject_ends_the_offer() -> None:
    client = make_client()
    say(client, "remind me to pay rent on friday")
    assert say(client, "no thanks") == "Okay, no alarm."
    say(client, "remind me to pay rent on friday")
    say(client, "what time is it")
    assert "What time" not in say(client, "yes 2pm") and client.get("/alarms").json() == []


def test_set_and_list_alarms_from_a_phrase_or_command() -> None:
    client = make_client()
    assert "What time" in say(client, "set an alarm")
    assert say(client, "set an alarm for 7am").startswith("Alright, an alarm is set for 7:00 AM")
    assert say(client, "/alarm thursday 2:30pm").startswith("Alright, an alarm is set for 2:30 PM")
    assert say(client, "/alarm") == "Usage: /alarm <when>"
    listing = say(client, "what alarms do I have")
    assert listing.count("Alarm at") == 2
    assert say(client, "/alarms") == listing
    assert len(client.get("/alarms").json()) == 2
    assert say(client, "wake me up in 30 minutes").startswith("Alright")
    assert say(client, "show my alarms").startswith("Your alarms:")


def test_remind_me_without_a_time_still_creates_no_offer() -> None:
    client = make_client()
    assert "alarm" not in say(client, "remind me to buy milk").lower()
    assert "What time" not in say(client, "yes 2pm")
