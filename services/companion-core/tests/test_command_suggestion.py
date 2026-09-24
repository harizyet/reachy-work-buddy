"""Phase 24b: the natural-language command-suggestion classifier is a
non-authoritative QoL layer on top of the ordinary conversation branch.
These tests drive it entirely through /conversation with a mocked LLM
transport (httpx.MockTransport), the same pattern test_websearch.py uses
for the grounding LLM call — no mocks of companion_core's own code."""

import json

import httpx
import pytest
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


def core_app(**kwargs):
    return create_app(
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
        **kwargs,
    )


TURN = {"session_id": "s1", "conversation_id": "c1", "channel": "web"}


def _classifier_json(intent: str, speech_act: str, confidence: float = 0.95) -> str:
    return json.dumps({"intent": intent, "speech_act": speech_act, "confidence": confidence})


def test_high_confidence_request_produces_a_suggestion_not_an_answer():
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        # First call is the classifier (system prompt asks for JSON only);
        # only reached if the classifier itself judges this a request.
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": _classifier_json("robot_standby", "request")}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "This should never be reached."}}]})

    client = TestClient(core_app(llm_transport=httpx.MockTransport(respond)))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    resp = client.post("/conversation", json={**TURN, "text": "Could you put Reachy to sleep?"})
    assert resp.status_code == 200
    assert "/reachy standby" in resp.json()["reply"]
    # Only the classifier call happened — the suggestion replaces the
    # model's answer, it doesn't run alongside it.
    assert len(calls) == 1


@pytest.mark.parametrize("speech_act", ["question", "negation", "hypothetical", "statement", "other"])
def test_non_request_speech_acts_never_suggest(speech_act: str):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": _classifier_json("robot_standby", speech_act)}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "A normal answer."}}]})

    client = TestClient(core_app(llm_transport=httpx.MockTransport(respond)))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    resp = client.post("/conversation", json={**TURN, "text": "How do I turn off Reachy?"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "A normal answer."
    assert len(calls) == 2


def test_low_confidence_request_never_suggests():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": _classifier_json("robot_standby", "request", confidence=0.4)}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "A normal answer."}}]})

    client = TestClient(core_app(llm_transport=httpx.MockTransport(respond)))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    resp = client.post("/conversation", json={**TURN, "text": "Maybe turn off Reachy?"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "A normal answer."


def test_classifier_failure_falls_back_silently_to_the_ordinary_answer():
    """Malformed/non-JSON classifier output must never surface as an
    error, and must never block the ordinary conversational reply."""
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "A normal answer."}}]})

    client = TestClient(core_app(llm_transport=httpx.MockTransport(respond)))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    resp = client.post("/conversation", json={**TURN, "text": "Turn off Reachy."})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "A normal answer."
    assert len(calls) == 2


def test_classifier_timeout_falls_back_silently_to_the_ordinary_answer():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "A normal answer."}}]})

    client = TestClient(core_app(llm_transport=httpx.MockTransport(respond)))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    resp = client.post("/conversation", json={**TURN, "text": "Turn off Reachy."})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "A normal answer."
    assert len(calls) == 2
    # The classifier's own failed call must not be recorded as a
    # user-visible provider error in the operator-facing usage ledger.
    assert client.get("/llm/usage").json()["summary"]["errors"] == 0


def test_classifier_is_never_called_for_text_unrelated_to_the_robot():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "A normal answer."}}]})

    client = TestClient(core_app(llm_transport=httpx.MockTransport(respond)))
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
    resp = client.post("/conversation", json={**TURN, "text": "What's the weather like?"})
    assert resp.status_code == 200
    assert len(calls) == 1


def test_explicit_command_never_reaches_the_classifier():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "unused"}}]})

    with TestClient(core_app(llm_transport=httpx.MockTransport(respond))) as client:
        client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})
        resp = client.post("/conversation", json={**TURN, "text": "/reachy standby"})
        assert resp.status_code == 200
        assert calls == []
