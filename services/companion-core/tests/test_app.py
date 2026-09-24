"""companion-core tests, chained through real (in-process) reachy-hub and
reachy-embodiment apps via nested httpx.ASGITransport — proves the full
Phase 4 chain (companion-core -> reachy-hub -> reachy-embodiment) without
mocks or real sockets. Both sibling services are importable here only
because uv installs all workspace members into one shared dev venv.
"""

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.models import EmailDraft
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app as create_hub_app
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.robot_registry import InMemoryRobotRegistry, Robot
from reachy_hub.session_store import InMemorySessionStore

_FAKE_EMBED_DIM = 16


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic bag-of-words stand-in for rag/embeddings.py's real
    model — fast, repeatable cosine-similarity results without loading
    real sentence-transformers weights (hashlib, not the builtin hash(),
    since str hashing is randomized per-process by default)."""
    vectors = []
    for text in texts:
        vector = [0.0] * _FAKE_EMBED_DIM
        for word in text.lower().split():
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % _FAKE_EMBED_DIM
            vector[bucket] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        vectors.append([v / norm for v in vector] if norm else vector)
    return vectors


_TEST_REMOTE_UI_TOKEN = "test-remote-token"


def make_chain(*, registered_robots: Sequence[Robot] = ()) -> TestClient:
    embodiment_app = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    registry = InMemoryRobotRegistry()
    registry._robots = {robot.robot_id: robot for robot in registered_robots}
    hub_app = create_hub_app(
        registry=registry,
        session_store=InMemorySessionStore(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=False,
        # Phase 16/ADR 0013: /robots/{id}/... became auth-gated; companion-
        # core's /debug/robots/... proxy needs the same shared token (see
        # hub_client.py) to keep reaching them.
        remote_ui_token=_TEST_REMOTE_UI_TOKEN,
    )
    # Records what would have been sent instead of opening a real SMTP
    # connection — tests assert against this list to prove the approval
    # gate (email/workflow.py) rather than trusting a mocked send call.
    sent_emails: list[EmailDraft] = []

    async def fake_send(draft: EmailDraft) -> None:
        sent_emails.append(draft)

    email_store = InMemoryEmailStore()
    core_app = create_app(
        hub_base_url="http://reachy-hub",
        transport=httpx.ASGITransport(app=hub_app),
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(embed_fn=_fake_embed),
        email_store=email_store,
        email_send_fn=fake_send,
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        # The real dispatch loop only ever sends what's actually due (10
        # minutes out by default) — disabled here so tests stay
        # deterministic; test_email_workflow.py covers the loop itself
        # with a real short-interval task, and tests below that need to
        # prove dispatch call dispatch_due_drafts directly with a
        # controlled `now` via client.email_store.
        run_email_dispatch_task=False,
        hub_bearer_token=_TEST_REMOTE_UI_TOKEN,
    )
    client = TestClient(core_app)
    client.sent_emails = sent_emails
    client.email_store = email_store
    return client


def test_health() -> None:
    with make_chain() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_debug_robot_state_returns_404_for_unregistered_robot() -> None:
    with make_chain() as client:
        resp = client.get("/debug/robots/desk-1/state")
        assert resp.status_code == 404


def test_conversation_turn_replies_and_counts_turns() -> None:
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "hello"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["turn_count"] == 1
        assert "hello" in body["reply"]

        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "telegram", "text": "and now?"},
        )
        assert resp.json()["turn_count"] == 2


def test_standby_command_parks_registered_robot_via_hub_and_embodiment() -> None:
    """Phase 24b: only the explicit `/reachy standby` command reaches the
    real standby path now — see the negative-example tests below for the
    free-form phrasing this used to (wrongly) actuate on."""
    with make_chain(registered_robots=[Robot(robot_id="desk-1", base_url="http://desk-1.local")]) as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "/reachy standby"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "standby" in body["reply"].lower()
        assert body["privacy"] == "public"

        # Proves this actually reached reachy-embodiment through the real
        # hub chain, not just a canned reply — the robot's own state
        # changed.
        state_resp = client.get("/debug/robots/desk-1/state")
        assert state_resp.json()["embodiment_state"] == "sleep"
        assert state_resp.json()["connected"] is False


def test_resume_command_wakes_registered_robot_via_hub_and_embodiment() -> None:
    with make_chain(registered_robots=[Robot(robot_id="desk-1", base_url="http://desk-1.local")]) as client:
        client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "/reachy standby"},
        )
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "/reachy wake"},
        )
        assert resp.status_code == 200
        assert "wak" in resp.json()["reply"].lower()

        state_resp = client.get("/debug/robots/desk-1/state")
        assert state_resp.json()["embodiment_state"] == "idle"
        assert state_resp.json()["connected"] is True


def test_telegram_alias_parses_to_the_same_command_as_the_namespaced_form() -> None:
    with make_chain(registered_robots=[Robot(robot_id="desk-1", base_url="http://desk-1.local")]) as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "telegram", "text": "/standby"},
        )
        assert resp.status_code == 200
        assert "standby" in resp.json()["reply"].lower()
        assert client.get("/debug/robots/desk-1/state").json()["embodiment_state"] == "sleep"


@pytest.mark.parametrize(("text", "typed_first", "expected"), [
    ("/reachy standby", None, ("idle", True)),
    ("/standby", None, ("idle", True)),
    ("/reachy wake", "/reachy standby", ("sleep", False)),
])
def test_spoken_command_text_never_actuates(text, typed_first, expected) -> None:
    """Phase 24c: a robot-microphone transcript arrives as VOICE. Commands
    are typed-only, so even the literal command syntax must not reach the
    real standby/resume chain from speech."""
    robot = Robot(robot_id="desk-1", base_url="http://desk-1.local")
    turn = {"session_id": "s1", "conversation_id": "c1", "channel": "reachy"}
    with make_chain(registered_robots=[robot]) as client:
        if typed_first:
            client.post("/conversation", json={**turn, "text": typed_first})
        resp = client.post("/conversation", json={**turn, "text": text, "input_modality": "voice"})
        assert resp.status_code == 200
        state = client.get("/debug/robots/desk-1/state").json()
        assert (state["embodiment_state"], state["connected"]) == expected


def test_standby_command_with_no_registered_robot_says_so() -> None:
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "/reachy standby"},
        )
        assert resp.status_code == 200
        assert "nothing to turn off" in resp.json()["reply"].lower()


def test_status_command_reports_registered_robots() -> None:
    with make_chain(registered_robots=[Robot(robot_id="desk-1", base_url="http://desk-1.local")]) as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "/reachy status"},
        )
        assert resp.status_code == 200
        assert "desk-1" in resp.json()["reply"]


@pytest.mark.parametrize("text", [
    "How do I turn off Reachy?",
    "Don't turn off Reachy.",
    "I don't want to turn off Reachy.",
    "Can you explain how to turn off Reachy?",
    "What happens if I turn off Reachy?",
    "Is it safe to turn off Reachy?",
    "How do I wake up Reachy?",
    "Don't wake up Reachy.",
])
def test_conversational_mentions_never_actuate_the_robot(text: str) -> None:
    """Phase 24b exit criterion: none of these calls the real
    standby/resume path — the retired substring matcher used to
    false-positive on every one of them."""
    with make_chain(registered_robots=[Robot(robot_id="desk-1", base_url="http://desk-1.local")]) as client:
        resp = client.post("/conversation", json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": text})
        assert resp.status_code == 200
        state_resp = client.get("/debug/robots/desk-1/state")
        assert state_resp.json()["embodiment_state"] != "sleep"


def test_conversation_turn_history_is_isolated_per_session() -> None:
    with make_chain() as client:
        client.post(
            "/conversation", json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "hi"}
        )
        resp = client.post(
            "/conversation", json={"session_id": "s2", "conversation_id": "c2", "channel": "reachy", "text": "hi"}
        )
        assert resp.json()["turn_count"] == 1  # a different session starts its own count


def test_whats_next_answers_from_real_calendar_data() -> None:
    """Phase 10 exit criterion: "What's next?" works, using genuinely
    stored calendar data rather than the generic placeholder reply."""
    with make_chain() as client:
        resp = client.get("/calendar/next")
        assert resp.status_code == 200
        assert resp.json() is None  # nothing stored yet

        create_resp = client.post(
            "/calendar/events",
            json={
                "title": "Team Standup",
                "start": "2099-01-05T10:00:00Z",
                "end": "2099-01-05T10:30:00Z",
                "location": "Room 4",
            },
        )
        assert create_resp.status_code == 200

        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what's next"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Team Standup" in body["reply"]
        assert "Room 4" in body["reply"]
        assert body["privacy"] == "work-private"


def test_whats_next_with_no_events_still_answers() -> None:
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what's next"},
        )
        assert resp.json()["reply"] == "You have nothing else on your calendar."


def test_todays_appointments_answers_from_real_calendar_data() -> None:
    with make_chain() as client:
        today = datetime.now(UTC)
        start = today.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
        end = today.replace(hour=9, minute=30, second=0, microsecond=0).isoformat()
        create_resp = client.post(
            "/calendar/events",
            json={"title": "Budget Review", "start": start, "end": end, "location": "Room 2"},
        )
        assert create_resp.status_code == 200

        resp = client.post(
            "/conversation",
            json={
                "session_id": "s1", "conversation_id": "c1", "channel": "reachy",
                "text": "what appointments do I have today",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Budget Review" in body["reply"]
        assert "Room 2" in body["reply"]
        assert body["privacy"] == "work-private"


def test_todays_appointments_with_no_events_still_answers() -> None:
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "today's schedule"},
        )
        assert resp.json()["reply"] == "You have nothing on your calendar today."


def test_calendar_list_and_free_busy() -> None:
    with make_chain() as client:
        client.post(
            "/calendar/events",
            json={"title": "Lunch", "start": "2099-01-05T12:00:00Z", "end": "2099-01-05T13:00:00Z"},
        )

        list_resp = client.get(
            "/calendar/events", params={"start": "2099-01-05T00:00:00Z", "end": "2099-01-06T00:00:00Z"}
        )
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["title"] == "Lunch"

        fb_resp = client.get(
            "/calendar/free-busy", params={"start": "2099-01-05T00:00:00Z", "end": "2099-01-06T00:00:00Z"}
        )
        assert fb_resp.status_code == 200
        assert "title" not in fb_resp.json()[0]  # free/busy reveals no event details
        assert fb_resp.json()[0]["start"] == "2099-01-05T12:00:00Z"


def test_reminders_due_endpoint() -> None:
    with make_chain() as client:
        soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        later = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
        client.post("/calendar/events", json={"title": "Soon", "start": soon, "end": soon})
        client.post("/calendar/events", json={"title": "Later", "start": later, "end": later})

        resp = client.get("/calendar/reminders/due", params={"within_minutes": 15})
        assert resp.status_code == 200
        reminders = resp.json()
        assert len(reminders) == 1
        assert "Soon" in reminders[0]["text"]
        assert reminders[0]["privacy"] == "work-private"
        assert reminders[0]["urgency"] == "urgent"


def test_reminders_due_grades_urgency_by_proximity() -> None:
    """Phase 17 (docs/adr/0014): reachy-hub's interruption engine needs a
    real NORMAL/URGENT distinction to demonstrate deferral with real
    calendar data — a reminder further than 5 minutes out is NORMAL, not
    URGENT."""
    with make_chain() as client:
        further_out = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        client.post("/calendar/events", json={"title": "Later standup", "start": further_out, "end": further_out})

        resp = client.get("/calendar/reminders/due", params={"within_minutes": 15})
        assert resp.status_code == 200
        reminders = resp.json()
        assert len(reminders) == 1
        assert reminders[0]["urgency"] == "normal"


def test_briefing_endpoint_combines_calendar_and_tasks() -> None:
    """Phase 18 (docs/adr/0015): GET /briefing composes real data across
    stores, not a placeholder — reachy-hub's POST /briefing/{user_id} just
    relays this list."""
    with make_chain() as client:
        soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        client.post("/calendar/events", json={"title": "Standup", "start": soon, "end": soon})
        client.post("/conversation", json={
            "session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remind me to buy milk"
        })

        resp = client.get("/briefing")
        assert resp.status_code == 200
        items = resp.json()
        categories = {item["category"] for item in items}
        assert "reminder" in categories
        assert "task" in categories
        assert any("buy milk" in item["text"] for item in items)
        # Reminders (urgency-graded) lead a prioritized list.
        assert items[0]["category"] == "reminder"
        assert items[0]["urgency"] == "urgent"


def test_agent_can_record_and_retrieve_a_follow_up() -> None:
    """Phase 11 exit criterion: agent can record and later retrieve
    explicit follow-ups, through the conversational path (not the direct
    API) — the actual thing a user would say."""
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "remind me to buy milk"},
        )
        assert resp.status_code == 200
        assert "buy milk" in resp.json()["reply"]

        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what are my tasks"},
        )
        assert "buy milk" in resp.json()["reply"]

        # Also retrievable via the direct API, not just conversationally.
        list_resp = client.get("/tasks")
        assert list_resp.status_code == 200
        assert list_resp.json()[0]["text"] == "buy milk"
        assert list_resp.json()[0]["status"] == "open"


def test_complete_and_search_tasks_conversationally() -> None:
    with make_chain() as client:
        client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "add task buy milk"},
        )
        client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "add task call dentist",
            },
        )

        complete_resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "complete task milk"},
        )
        assert "buy milk" in complete_resp.json()["reply"]

        # Completed task no longer shows up in the open-task list.
        list_resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what are my tasks"},
        )
        assert "buy milk" not in list_resp.json()["reply"]
        assert "call dentist" in list_resp.json()["reply"]

        search_resp = client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "search tasks for milk",
            },
        )
        assert "buy milk" in search_resp.json()["reply"]

        # search_tasks doesn't filter by status — the completed task is
        # still findable, unlike the open-tasks list above.
        assert client.get("/tasks/search", params={"q": "milk"}).json()[0]["status"] == "done"


def test_complete_unmatched_task_via_conversation() -> None:
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "complete task something that does not exist",
            },
        )
        assert "couldn't find" in resp.json()["reply"]


def test_task_endpoints_directly() -> None:
    with make_chain() as client:
        create_resp = client.post("/tasks", json={"text": "buy milk"})
        assert create_resp.status_code == 200
        task_id = create_resp.json()["id"]

        complete_resp = client.post(f"/tasks/{task_id}/complete")
        assert complete_resp.status_code == 200
        assert complete_resp.json()["status"] == "done"

        assert client.post("/tasks/nonexistent-id/complete").status_code == 404


def test_agent_can_remember_and_recall_a_work_fact_without_transcript_dumping() -> None:
    """Phase 12 exit criterion: "Stored work fact can be recalled later
    without transcript dumping" — recall must come from MemoryStore, not
    from replaying the session's conversation history."""
    with make_chain() as client:
        capture_resp = client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "remember that my manager's email is alice@example.com",
            },
        )
        assert capture_resp.status_code == 200
        assert "alice@example.com" in capture_resp.json()["reply"]

        # Unrelated turns that should never surface in the recall reply.
        client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what's the weather"},
        )
        client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "remember that I like green tea",
            },
        )

        recall_resp = client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "do you remember alice@example.com",
            },
        )
        assert recall_resp.status_code == 200
        body = recall_resp.json()
        assert "alice@example.com" in body["reply"]
        assert "green tea" not in body["reply"]  # only the matching fact, not a transcript dump
        assert "weather" not in body["reply"]
        assert body["privacy"] == "work-private"

        # Also retrievable via the direct API.
        recall_api = client.get("/memories/recall", params={"q": "alice@example.com"})
        assert recall_api.status_code == 200
        assert len(recall_api.json()) == 1
        assert recall_api.json()[0]["content"] == "my manager's email is alice@example.com"


def test_memory_endpoints_directly() -> None:
    with make_chain() as client:
        create_resp = client.post("/memories", json={"content": "meeting: project codename is Falcon"})
        assert create_resp.status_code == 200
        memory_id = create_resp.json()["id"]
        assert create_resp.json()["sensitivity"] == "work-private"

        list_resp = client.get("/memories")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        # docs/adr/0011: deleting a memory is now a two-step, confirmed API.
        request_resp = client.post(f"/memories/{memory_id}/request-forget")
        assert request_resp.status_code == 200
        confirmation_id = request_resp.json()["id"]

        confirm_resp = client.post(
            f"/memories/{memory_id}/forget/confirm", json={"confirmation_id": confirmation_id}
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["forgotten_at"] is not None
        assert client.get("/memories").json() == []

        # A second confirm attempt with the same (now-consumed) id fails.
        assert (
            client.post(f"/memories/{memory_id}/forget/confirm", json={"confirmation_id": confirmation_id}).status_code
            == 404
        )

        # The undo: restoring brings it back into /memories.
        restore_resp = client.post(f"/memories/{memory_id}/restore")
        assert restore_resp.status_code == 200
        assert restore_resp.json()["forgotten_at"] is None
        assert len(client.get("/memories").json()) == 1


def test_agent_answers_conversationally_with_document_and_section_provenance() -> None:
    """Phase 13 exit criterion: "Answers identify their supporting
    document/section/page where available"."""
    with make_chain() as client:
        ingest_resp = client.post(
            "/documents",
            json={
                "title": "Vacation Policy",
                "content": "# Requesting time off\nSubmit a request in Workday at least two weeks in advance.",
                "source": "hr.md",
            },
        )
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()[0]["section"] == "Requesting time off"

        resp = client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "search docs for requesting time off",
            },
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        assert "Vacation Policy" in reply  # document provenance
        assert "Requesting time off" in reply  # section provenance
        assert "Workday" in reply  # the actual answer content

        # Also retrievable via the direct API.
        search_resp = client.get("/documents/search", params={"q": "time off"})
        assert search_resp.status_code == 200
        assert search_resp.json()[0]["chunk"]["document_title"] == "Vacation Policy"


def test_rag_query_with_no_documents_ingested_says_so() -> None:
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "look up parking"},
        )
        assert "couldn't find" in resp.json()["reply"]


def test_document_endpoints_directly() -> None:
    with make_chain() as client:
        client.post("/documents", json={"title": "Doc A", "content": "alpha content"})
        client.post("/documents", json={"title": "Doc B", "content": "beta content"})

        list_resp = client.get("/documents")
        assert list_resp.status_code == 200
        assert list_resp.json() == ["Doc A", "Doc B"]


def test_agent_cannot_send_email_without_approval_and_send_is_delayed() -> None:
    """Phase 14 exit criterion: "No code path sends mail without approval
    gate" — drafted conversationally, sending before approval is refused
    and nothing is dispatched. docs/adr/0011 extends this: even once
    approved, "send draft X" only queues a delayed dispatch, cancellable
    conversationally, and voice can't approve or trigger a send at all."""
    with make_chain() as client:
        draft_resp = client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "draft email to bob@example.com about the quarterly numbers",
            },
        )
        assert draft_resp.status_code == 200
        reply = draft_resp.json()["reply"]
        assert "bob@example.com" in reply
        assert "approve" in reply.lower()

        # Sending before approval must fail, and must not dispatch anything.
        premature_send = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "send draft bob"},
        )
        assert premature_send.status_code == 200
        assert "approval" in premature_send.json()["reply"].lower()
        assert client.sent_emails == []

        # Voice can't approve — text-only, docs/adr/0011.
        voice_approve = client.post(
            "/conversation",
            json={
                "session_id": "s1",
                "conversation_id": "c1",
                "channel": "reachy",
                "text": "approve draft bob",
                "input_modality": "voice",
            },
        )
        assert "voice" in voice_approve.json()["reply"].lower()
        assert "text" in voice_approve.json()["reply"].lower()

        approve_resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "approve draft bob"},
        )
        assert "Approved" in approve_resp.json()["reply"]

        send_resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "send draft bob"},
        )
        reply = send_resp.json()["reply"]
        assert "10 minutes" in reply
        assert "cancel send" in reply.lower()
        assert client.sent_emails == []  # queued, not dispatched

        assert client.get("/emails/drafts").json()[0]["status"] == "queued"

        # Cancelling (any modality) reverts the queue — no dispatch will
        # happen, proven at the workflow level in test_email_workflow.py.
        cancel_resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "cancel send bob"},
        )
        assert "Cancelled" in cancel_resp.json()["reply"]
        assert client.get("/emails/drafts").json()[0]["status"] == "approved"


def test_email_direct_api_delayed_send_gate_and_dispatch() -> None:
    async def run() -> None:
        from companion_core.email.workflow import dispatch_due_drafts

        with make_chain() as client:
            draft_resp = client.post(
                "/emails/drafts", json={"to": "alice@example.com", "subject": "Hi", "body": "hello there"}
            )
            assert draft_resp.status_code == 200
            draft_id = draft_resp.json()["id"]

            # Sending an unapproved draft is rejected, not silently dispatched.
            send_before_approval = client.post(f"/emails/drafts/{draft_id}/send")
            assert send_before_approval.status_code == 409
            assert client.sent_emails == []

            approve_resp = client.post(f"/emails/drafts/{draft_id}/approve")
            assert approve_resp.status_code == 200
            assert approve_resp.json()["status"] == "approved"

            send_resp = client.post(f"/emails/drafts/{draft_id}/send")
            assert send_resp.status_code == 200
            assert send_resp.json()["status"] == "queued"  # not "sent" — delayed
            assert send_resp.json()["dispatch_at"] is not None
            assert client.sent_emails == []

            assert client.post("/emails/drafts/nonexistent/send").status_code == 404

            # Cancel undoes the queue — back to approved, nothing sent even
            # once the original dispatch_at has clearly passed.
            cancel_resp = client.post(f"/emails/drafts/{draft_id}/cancel-send")
            assert cancel_resp.status_code == 200
            assert cancel_resp.json()["status"] == "approved"

            async def record_send(draft) -> None:
                client.sent_emails.append(draft)

            future = datetime.now(UTC) + timedelta(minutes=30)
            dispatched = await dispatch_due_drafts(client.email_store, send_fn=record_send, now=future)
            assert dispatched == 0
            assert client.sent_emails == []

            # Re-queue and actually let it dispatch this time.
            client.post(f"/emails/drafts/{draft_id}/send")
            dispatched = await dispatch_due_drafts(client.email_store, send_fn=record_send, now=future)
            assert dispatched == 1
            assert len(client.sent_emails) == 1
            assert (await client.email_store.get_draft(draft_id)).status.value == "sent"

    asyncio.run(run())


def test_email_inbox_seeding_and_listing() -> None:
    with make_chain() as client:
        seed_resp = client.post(
            "/emails/received", json={"sender": "boss@example.com", "subject": "Q3 report", "body": "see attached"}
        )
        assert seed_resp.status_code == 200

        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what's in my inbox"},
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        assert "Q3 report" in reply
        assert "boss@example.com" in reply
        assert resp.json()["privacy"] == "work-private"

        assert client.get("/emails/received").json()[0]["subject"] == "Q3 report"


def _make_bare_core_app() -> FastAPI:
    """A minimal companion-core app (in-memory stores, no reachy-hub chain
    needed) for testing create_app's own construction behavior directly —
    used here for EMAIL_SEND_DELAY_SECONDS resolution, not the conversation
    flow the rest of this file chains through reachy-hub for."""
    return create_app(
        transport=httpx.ASGITransport(app=create_hub_app(run_heartbeat_task=False)),
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(embed_fn=_fake_embed),
        email_store=InMemoryEmailStore(),
        email_send_fn=lambda draft: asyncio.sleep(0),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
    )


def _queue_a_draft_and_get_dispatch_at(client: TestClient) -> datetime:
    draft_resp = client.post("/emails/drafts", json={"to": "a@example.com", "subject": "Hi", "body": "hi"})
    draft_id = draft_resp.json()["id"]
    client.post(f"/emails/drafts/{draft_id}/approve")
    send_resp = client.post(f"/emails/drafts/{draft_id}/send")
    assert send_resp.status_code == 200
    return datetime.fromisoformat(send_resp.json()["dispatch_at"])


def test_email_send_delay_defaults_to_ten_minutes_when_env_unset() -> None:
    with TestClient(_make_bare_core_app()) as client:
        gap = _queue_a_draft_and_get_dispatch_at(client) - datetime.now(UTC)
        assert timedelta(minutes=9) < gap < timedelta(minutes=11)


def test_email_send_delay_env_override_shortens_it(monkeypatch) -> None:
    """ADR 0011's ~10-minute default is a real-time cost during manual/live
    testing — EMAIL_SEND_DELAY_SECONDS lets it be shortened without a code
    change."""
    monkeypatch.setenv("EMAIL_SEND_DELAY_SECONDS", "5")
    with TestClient(_make_bare_core_app()) as client:
        gap = _queue_a_draft_and_get_dispatch_at(client) - datetime.now(UTC)
        assert gap < timedelta(seconds=30)  # the overridden 5s, not the real 10 minutes


def test_email_send_delay_env_empty_string_falls_through_to_default(monkeypatch) -> None:
    """docker-compose's `${VAR:-}` produces an empty string, not an unset
    var, when EMAIL_SEND_DELAY_SECONDS isn't set in .env — int("") would
    otherwise crash instead of falling through to the real default."""
    monkeypatch.setenv("EMAIL_SEND_DELAY_SECONDS", "")
    with TestClient(_make_bare_core_app()) as client:
        gap = _queue_a_draft_and_get_dispatch_at(client) - datetime.now(UTC)
        assert timedelta(minutes=9) < gap < timedelta(minutes=11)


def test_debug_trigger_behaviour_reaches_reachy_embodiment_through_the_hub() -> None:
    # The robot is registered directly with reachy-hub, not through
    # companion-core: companion-core has no /robots endpoint of its own
    # (ADR 0001 — robot registry belongs to reachy-hub, not companion-core).
    robot = Robot(robot_id="desk-1", base_url="http://desk-1.local")
    with make_chain(registered_robots=[robot]) as client:
        resp = client.post("/debug/robots/desk-1/behaviour/greeting")
        assert resp.status_code == 200
        assert resp.json()["last_behaviour"] == "greeting"

        state_resp = client.get("/debug/robots/desk-1/state")
        assert state_resp.status_code == 200
        assert state_resp.json()["last_behaviour"] == "greeting"
