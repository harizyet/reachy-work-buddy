"""Which privacy labels carry forward through a conversation (Phase 24d).

The model's own wording is never classified (owner, 2026-09-26); private
data that stays in the conversation history keeps later replies private.
"""

import httpx
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

TURN = {"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "input_modality": "voice"}


def chat_client(*replies: str, seen: list[str] | None = None) -> TestClient:
    queued = list(replies)

    def respond(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.read().decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": queued.pop(0)}}]})

    client = TestClient(create_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
        llm_transport=httpx.MockTransport(respond),
    ))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    return client


def say(client: TestClient, text: str) -> str:
    resp = client.post("/conversation", json={**TURN, "text": text})
    assert resp.status_code == 200
    return resp.json()["privacy"]


def test_keywords_in_a_generated_reply_do_not_withhold_it() -> None:
    # 24d: a 5G answer mentioning "medical" silenced the robot. 24e physical
    # run: a morning-routine answer "reviewing your schedule" was withheld.
    client = chat_client(
        "5G is used in medical imaging and factories.",
        "Try stretching, then start by reviewing your schedule.",
        "Teal.",
    )
    assert say(client, "What can you tell me about 5G?") == "public"
    assert say(client, "What's a good way to start the morning?") == "public"
    assert say(client, "What colour did I pick?") == "public"


def test_a_general_work_question_is_public_but_the_owners_own_is_not() -> None:
    client = chat_client("Open Outlook, then choose New Meeting.", "Noted.", "Okay.")
    assert say(client, "How do I schedule a meeting on Outlook?") == "public"
    assert say(client, "I have a meeting at noon.") == "work-private"
    assert say(client, "What's my salary?") == "sensitive"


def test_calendar_results_keep_later_generated_replies_private() -> None:
    client = chat_client("It's the one I just mentioned.")
    client.post("/calendar/events", json={
        "title": "Dentist", "start": "2099-01-05T12:00:00Z", "end": "2099-01-05T13:00:00Z",
    })
    assert say(client, "What's my next event?") == "work-private"
    assert say(client, "Tell me more about it") == "work-private"


def test_the_owners_own_sensitive_statement_keeps_later_replies_private() -> None:
    # The follow-up reply can repeat the value without the keyword.
    client = chat_client("Noted.", "It was hunter2.")
    assert say(client, "My password is hunter2") == "sensitive"
    assert say(client, "What was it again?") == "sensitive"


def test_a_carried_label_expires_once_its_message_leaves_the_context() -> None:
    # 24e physical run: one "meeting" in a question kept every later reply
    # private until core restarted. Owner decision 2026-09-26: the label
    # lasts only while the model can still see that message.
    from companion_core.conversation import CONTEXT_MESSAGES

    # The private reply is message 2; filler turn k (0-based) runs with
    # 3 + 2k messages, so the reply is out of the window from this turn on.
    expires_at = (CONTEXT_MESSAGES - 1) // 2
    client = chat_client("Noted.", *["Okay."] * (expires_at + 1))
    assert say(client, "I have a meeting at noon.") == "work-private"
    labels = [say(client, f"Filler question number {n}?") for n in range(expires_at + 1)]
    assert set(labels[:expires_at]) == {"work-private"}  # still in the model's context
    assert labels[expires_at] == "public"  # scrolled out: the robot may speak again


def test_natural_email_actions_get_a_fixed_spoken_refusal_not_a_false_claim() -> None:
    # 24e physical run: "Delete all my emails." and "Yes, send it." reached
    # the model, which claimed actions that never happened; every reply was
    # also withheld because the request mentioned email.
    client = chat_client()  # no model reply queued: the model must not be called
    for text in ("Delete all my emails.", "Yes, send it.", "Can you send an email to Bob?"):
        resp = client.post("/conversation", json={**TURN, "text": text})
        body = resp.json()
        assert "I can't send, approve or delete email by voice" in body["reply"]
        assert "haven't done anything" in body["reply"]
        assert body["privacy"] == "public"  # fixed text: the robot may speak it
    assert client.get("/emails/drafts").json() == []


def test_the_model_is_told_it_cannot_act() -> None:
    from companion_core.app import ACTION_BOUNDARY_INSTRUCTION

    seen: list[str] = []
    client = chat_client("Four.", seen=seen)
    say(client, "What is two plus two?")
    assert any(ACTION_BOUNDARY_INSTRUCTION in body for body in seen)
