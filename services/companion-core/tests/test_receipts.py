"""Phase 39: authoritative action receipts and persona-toned acknowledgements."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.render import TEMPLATES, render
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.persona import TONE_INSTRUCTIONS


def make_client() -> TestClient:
    return TestClient(
        create_app(
            calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(),
            planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(),
            run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(),
            email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
            persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
            run_email_dispatch_task=False,
        )
    )


def _say(client: TestClient, text: str, channel: str = "web", session: str = "s1") -> str:
    response = client.post(
        "/conversation",
        json={"session_id": session, "conversation_id": "c", "channel": channel, "text": text},
    )
    assert response.status_code == 200, response.text
    return response.json()["reply"]


def test_every_event_has_a_template_for_every_tone_and_the_same_placeholders() -> None:
    for event, options in TEMPLATES.items():
        assert set(options) == set(TONE_INSTRUCTIONS) | {"default"}, event
        fields = {tone: set(re.findall(r"{(\w+)}", text)) for tone, text in options.items()}
        assert len({frozenset(f) for f in fields.values()}) == 1, event


def test_default_wording_is_the_original_wording() -> None:
    assert render("task_captured", "default", text="buy milk") == "Got it, I'll remember: 'buy milk'."
    assert render("task_completed", "default", text="x") == "Marked 'x' as done."
    assert render("memory_captured", "default", content="c") == "I'll remember that: c."
    assert render("alarm_declined", "default") == "Okay, no alarm."
    assert render("task_captured", "unknown-tone", text="x") == render("task_captured", "default", text="x")


@pytest.mark.parametrize("tone", [t for t in TONE_INSTRUCTIONS if t != "default"])
def test_tone_changes_wording_but_never_the_facts_or_the_receipt(tone: str) -> None:
    client = make_client()
    client.put("/settings/persona", json={"tone": tone})
    reply = _say(client, "remind me to buy milk")
    assert "buy milk" in reply
    receipts = client.get("/receipts").json()
    assert receipts[0]["action_type"] == "task.created"
    assert receipts[0]["fields"] == {"Task": "buy milk"}


def test_task_capture_and_complete_record_receipts_and_notify_off_telegram() -> None:
    client = make_client()
    assert _say(client, "remind me to call mum") == "Got it, I'll remember: 'call mum'."
    _say(client, "done with call mum")
    kinds = [r["action_type"] for r in client.get("/receipts").json()]
    assert kinds == ["task.completed", "task.created"]
    # a web turn is pushed to Telegram; a Telegram turn is not (already in the chat)
    assert len(client.get("/receipts/pending").json()) == 2
    assert client.get("/receipts/pending").json() == []
    _say(client, "remind me to water plants", channel="telegram", session="s2")
    assert client.get("/receipts/pending").json() == []


def test_a_failed_lookup_records_no_receipt() -> None:
    client = make_client()
    assert "couldn't find" in _say(client, "done with nothing matching")
    assert client.get("/receipts").json() == []


def test_alarm_creation_and_cancel_receipts_do_not_notify_but_delivery_does() -> None:
    client = make_client()
    due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    alarm = client.post("/alarms", json={"label": "wake", "due_at": due}).json()
    client.delete(f"/alarms/{alarm['id']}")
    assert [r["action_type"] for r in client.get("/receipts").json()] == ["alarm.cancelled", "alarm.created"]
    assert client.get("/receipts/pending").json() == []

    second = client.post("/alarms", json={"label": "nap", "due_at": due}).json()
    client.post(f"/alarms/{second['id']}/delivery", json={"delivery": "played"})
    client.post(f"/alarms/{second['id']}/delivery", json={"delivery": "failed: no audio"})
    pending = client.get("/receipts/pending").json()
    assert [(r["action_type"], r["status"]) for r in pending] == [("alarm.delivered", "success")]
    failed = client.get("/receipts").json()[0]
    assert failed["status"] == "failed" and failed["failure_reason"] == "failed: no audio"


def test_spoken_alarm_creation_receipt_is_separate_from_delivery() -> None:
    client = make_client()
    _say(client, "set an alarm for 11pm tomorrow")
    receipt = client.get("/receipts").json()[0]
    assert receipt["action_type"] == "alarm.created" and receipt["notify"] is True
    assert receipt["fields"]["Label"] == "Alarm"
