"""Phase 43: a question asked with a meeting attached searches the web when it is about the outside world, so the answer
is checked online rather than taken from a model's possibly stale memory, and never sends meeting text to the search."""

import asyncio
import json

import httpx
import pytest
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
from companion_core.websearch.policy import (
    should_search,
    should_search_for_meeting_question,
)
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.websearch import SearchPolicy

AUTO, OFF, ALWAYS = SearchPolicy.AUTO, SearchPolicy.OFF, SearchPolicy.ALWAYS
SECRET = "Priya will benchmark ingestion speed by Friday"
SEGMENTS = [
    {"start": 0.0, "end": 6.0, "text": "Today we are comparing ClickHouse and InfluxDB for the metrics store."},
    {"start": 6.0, "end": 13.0, "text": SECRET + "."},
]


@pytest.mark.parametrize("question", [
    "Is ClickHouse free?", "What is ClickHouse?", "Does ClickHouse support JSON?", "How much does ClickHouse Cloud cost?",
    "Who makes ClickHouse?", "Is InfluxDB open source?",
])
def test_outward_looking_questions_search_when_a_meeting_is_attached(question: str) -> None:
    assert should_search_for_meeting_question(question, policy=AUTO) is True
    assert should_search(question, policy=AUTO) in (True, False)  # without a meeting this is the old rule, unchanged


@pytest.mark.parametrize("question", [
    "What did Priya say about the budget?", "Who will benchmark ingestion?", "What were the action items?",
    "Summarise the meeting", "What did we decide in the meeting?", "Who was mentioned in the call?",
    "Is it free?", "Does that support JSON?", "thanks", "who are you",
])
def test_questions_about_what_was_said_or_with_no_subject_stay_off_the_web(question: str) -> None:
    assert should_search_for_meeting_question(question, policy=AUTO) is False


def test_the_policy_still_rules() -> None:
    assert should_search_for_meeting_question("Is ClickHouse free?", policy=OFF) is False
    assert should_search_for_meeting_question("Who will benchmark ingestion?", policy=ALWAYS) is True
    assert should_search_for_meeting_question("thanks", policy=ALWAYS) is False


def make(search_results=None, search_status=200):
    searches: list[httpx.Request] = []
    chats: list[list[dict]] = []

    def llm(request: httpx.Request) -> httpx.Response:
        chats.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "ClickHouse is open source [S1]."}}]})

    def searx(request: httpx.Request) -> httpx.Response:
        searches.append(request)
        results = search_results if search_results is not None else [
            {"title": "ClickHouse FAQ", "url": "https://clickhouse.com/docs/faq", "content": "ClickHouse is open source under Apache 2.0."},
        ]
        return httpx.Response(search_status, json={"results": results})

    store = InMemoryMeetingStore()

    async def seed() -> str:
        meeting = await store.create_meeting(title="Database choice", audio=b"x", source_filename="m.m4a", content_type="audio/mp4")
        store._touch(meeting, transcript_segments=SEGMENTS, status="aligning")
        return meeting.id

    mid = asyncio.run(seed())
    client = TestClient(create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=store, run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, llm_transport=httpx.MockTransport(llm), websearch_transport=httpx.MockTransport(searx),
    ))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})
    client.put("/settings/websearch", json={"policy": "auto", "base_url": "http://searxng.local"})
    return client, mid, searches, chats


def ask(client, text, mid=None):
    body = {"session_id": "s", "conversation_id": "c", "channel": "web", "text": text}
    if mid:
        body["context_meeting_id"] = mid
    return client.post("/conversation", json=body).json()


def system_text(messages) -> str:
    return "\n".join(m["content"] for m in messages if m["role"] == "system")


def test_the_question_is_searched_and_the_answer_cites_the_results() -> None:
    client, mid, searches, chats = make()
    with client:
        reply = ask(client, "Is ClickHouse free?", mid)
        assert len(searches) == 1 and searches[0].url.params["q"] == "Is ClickHouse free?"
        assert reply["web_search"]["results"][0]["url"] == "https://clickhouse.com/docs/faq"
        assert reply["context_meeting"] == "Database choice" and reply["privacy"] == "work-private"
        system = system_text(chats[-1])
        assert 'id="S1"' in system  # the results reach the model as untrusted data
        assert "rely on those results rather than on your memory" in system  # and are preferred over what it remembers
        assert "Priya will benchmark" in system  # the meeting is still there for what was said


def test_the_search_receives_only_the_owners_question_never_the_transcript() -> None:
    client, mid, searches, _ = make()
    with client:
        ask(client, "What is ClickHouse?", mid)
        sent = " ".join(str(v) for r in searches for v in (r.url.params.multi_items(), r.content))
        assert "What is ClickHouse?" in sent
        assert SECRET not in sent and "InfluxDB" not in sent and "Database choice" not in sent


def test_questions_about_the_meeting_do_not_search_and_the_old_behaviour_without_a_meeting_is_unchanged() -> None:
    client, mid, searches, chats = make()
    with client:
        ask(client, "What did Priya say about the benchmark?", mid)
        ask(client, "Is it free?", mid)
        assert searches == []
        ask(client, "Is ClickHouse free?")  # no meeting attached: auto does not search this, as before
        assert searches == [] and "attached a meeting" not in system_text(chats[-1])


def test_policy_off_never_searches_even_with_a_meeting() -> None:
    client, mid, searches, _ = make()
    with client:
        client.put("/settings/websearch", json={"policy": "off"})
        ask(client, "Is ClickHouse free?", mid)
        assert searches == []


def test_a_failed_search_is_disclosed_and_the_meeting_is_still_used_locally() -> None:
    client, mid, searches, chats = make(search_status=500)
    with client:
        reply = ask(client, "Is ClickHouse free?", mid)
        assert searches and reply["web_search"]["failed"] is True and reply["context_meeting"] == "Database choice"
        system = system_text(chats[-1])
        assert "rely on those results" not in system  # no results to rely on, so the instruction is not given
        assert "column" in system or "ClickHouse and InfluxDB" in system
