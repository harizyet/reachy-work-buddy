"""Which privacy labels carry forward through a conversation (Phase 24d).

A keyword in the model's own wording labels only that reply; private data
that stays in the conversation history keeps later replies private.
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


def chat_client(*replies: str) -> TestClient:
    queued = list(replies)

    def respond(request: httpx.Request) -> httpx.Response:
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


def test_keyword_in_a_generated_reply_labels_only_that_reply() -> None:
    # The live 24d failure: a general 5G answer mentioning medical uses
    # silenced the robot for every later turn.
    client = chat_client("5G is used in medical imaging and factories.", "Four.", "Teal.")
    assert say(client, "What can you tell me about 5G?") == "sensitive"
    assert say(client, "What is two plus two?") == "public"
    assert say(client, "What colour did I pick?") == "public"


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
