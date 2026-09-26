"""Time and date questions answered from the clock (owner decision,
2026-09-26, 24e physical run)."""

import re
from datetime import UTC, datetime

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.clock_intent import (
    format_clock_reply,
    is_remote_time_query,
    match_local_clock,
)
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient


@pytest.mark.parametrize(("text", "kind"), [
    ("What time is it?", "time"),
    ("Reachy, what time is it right now?", "time"),
    ("Do you know what time it is?", "time"),
    ("What's the time at the moment?", "time"),
    ("What time is it here?", "time"),
    ("What's the date today?", "date"),
    ("What day is it today?", "date"),
])
def test_local_clock_questions(text, kind):
    assert match_local_clock(text) == kind
    assert not is_remote_time_query(text)


@pytest.mark.parametrize("text", [
    "What time is it in Tokyo now?", "What's the time in New York?", "What time is it in the UK?",
])
def test_another_place_is_not_the_local_clock(text):
    assert match_local_clock(text) is None
    assert is_remote_time_query(text)


@pytest.mark.parametrize("text", [
    "What is the time difference between London and Paris?",
    "What's the date of the election?",
    "What time is my meeting?",
    "How do I schedule a meeting on Outlook?",
])
def test_other_questions_about_time_are_not_clock_questions(text):
    assert match_local_clock(text) is None
    assert not is_remote_time_query(text)


def test_replies_use_the_owners_timezone():
    now = datetime(2026, 9, 26, 14, 5, tzinfo=UTC)
    assert format_clock_reply("time", now, "Asia/Singapore") == "It's 10:05 PM."
    assert format_clock_reply("time", now, "UTC") == "It's 2:05 PM."
    assert format_clock_reply("date", now, "Asia/Singapore") == "It's Saturday, 26 September 2026."
    assert format_clock_reply("time", datetime(2026, 9, 26, 16, 30, tzinfo=UTC), "Asia/Singapore") == "It's 12:30 AM."


def test_the_conversation_answers_the_local_time_without_the_model():
    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the model must not be called")

    client = TestClient(create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, llm_transport=httpx.MockTransport(respond),
    ))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    body = client.post("/conversation", json={
        "session_id": "s1", "conversation_id": "c1", "channel": "reachy", "input_modality": "voice",
        "text": "What time is it?",
    }).json()
    assert re.fullmatch(r"It's \d{1,2}:\d{2} (AM|PM)\.", body["reply"])
    assert body["privacy"] == "public"
    assert body.get("web_search") is None
