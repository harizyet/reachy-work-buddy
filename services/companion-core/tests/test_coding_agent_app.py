"""Phase 29: companion-core's conversation branch answering owner questions
about coding-agent sessions, and the /coding-agents/completions/due route
reachy-hub polls. Chained against a real in-process coding-agent-service
app via httpx.ASGITransport — a sibling workspace member, importable here
only because uv installs every workspace member into one shared dev venv;
production companion-core images do not include its code.
"""

import httpx
from coding_agent_service.app import create_app as create_coding_agent_app
from coding_agent_service.providers import SimulatedProvider
from coding_agent_service.store import InMemoryCodingAgentStore
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

SERVICE_TOKEN = "fixture-coding-agent-token"


def _coding_agent_app():
    return create_coding_agent_app(
        store=InMemoryCodingAgentStore(),
        providers={"simulated": SimulatedProvider()},
        service_token=SERVICE_TOKEN,
    )


def _core_app(coding_agent_app):
    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the model must not be called for a coding-agent status/usage question")

    return create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, llm_transport=httpx.MockTransport(respond),
        coding_agent_base_url="http://coding-agent-service",
        coding_agent_transport=httpx.ASGITransport(app=coding_agent_app),
        coding_agent_service_token=SERVICE_TOKEN,
    )


def _turn(client: TestClient, text: str) -> dict:
    return client.post("/conversation", json={
        "session_id": "s1", "conversation_id": "c1", "channel": "telegram", "input_modality": "text",
        "text": text,
    }).json()


def test_status_question_reports_a_real_session_without_the_model() -> None:
    coding_agent_app = _coding_agent_app()
    coding_agent_client = TestClient(coding_agent_app)
    headers = {"X-Reachy-Coding-Agent-Service-Token": SERVICE_TOKEN}
    project = coding_agent_client.post(
        "/projects", headers=headers,
        json={"name": "Reachy Work Buddy", "repository_path": "/x", "provider": "simulated"},
    ).json()
    coding_agent_client.post(
        "/sessions", headers=headers,
        json={"project_id": project["id"], "task_summary": "Refactor module X", "owner_user_id": "owner-1"},
    )

    with TestClient(_core_app(coding_agent_app)) as client:
        body = _turn(client, "is my coding session done")
    assert "Refactor module X" in body["reply"]
    assert "finished" in body["reply"]
    assert body["privacy"] == "work-private"


def test_status_question_with_no_sessions() -> None:
    with TestClient(_core_app(_coding_agent_app())) as client:
        body = _turn(client, "is my claude session done")
    assert body["reply"] == "You have no coding-agent sessions."


def test_usage_question_reports_only_active_sessions() -> None:
    coding_agent_app = _coding_agent_app()
    coding_agent_client = TestClient(coding_agent_app)
    headers = {"X-Reachy-Coding-Agent-Service-Token": SERVICE_TOKEN}
    project = coding_agent_client.post(
        "/projects", headers=headers,
        json={"name": "X", "repository_path": "/x", "provider": "simulated"},
    ).json()
    coding_agent_client.post(
        "/sessions", headers=headers,
        json={"project_id": project["id"], "task_summary": "ask: pick one", "owner_user_id": "owner-1"},
    )

    with TestClient(_core_app(coding_agent_app)) as client:
        body = _turn(client, "what's my claude usage")
    # SimulatedProvider reports no usage dimensions — a real provider's
    # absence of a dimension must never be reported as zero (29.26).
    assert "no usage information available yet" in body["reply"]


def test_completions_due_claims_each_session_only_once() -> None:
    coding_agent_app = _coding_agent_app()
    coding_agent_client = TestClient(coding_agent_app)
    headers = {"X-Reachy-Coding-Agent-Service-Token": SERVICE_TOKEN}
    project = coding_agent_client.post(
        "/projects", headers=headers,
        json={"name": "X", "repository_path": "/x", "provider": "simulated"},
    ).json()
    coding_agent_client.post(
        "/sessions", headers=headers,
        json={"project_id": project["id"], "task_summary": "Refactor module X", "owner_user_id": "owner-7"},
    )

    with TestClient(_core_app(coding_agent_app)) as client:
        first = client.get("/coding-agents/completions/due").json()
        second = client.get("/coding-agents/completions/due").json()
    assert len(first) == 1
    assert first[0]["owner_user_id"] == "owner-7"
    assert "Refactor module X" in first[0]["text"]
    assert second == []


def test_completions_due_skips_sessions_still_running() -> None:
    coding_agent_app = _coding_agent_app()
    coding_agent_client = TestClient(coding_agent_app)
    headers = {"X-Reachy-Coding-Agent-Service-Token": SERVICE_TOKEN}
    project = coding_agent_client.post(
        "/projects", headers=headers,
        json={"name": "X", "repository_path": "/x", "provider": "simulated"},
    ).json()
    coding_agent_client.post(
        "/sessions", headers=headers,
        json={"project_id": project["id"], "task_summary": "ask: pick one", "owner_user_id": "owner-1"},
    )

    with TestClient(_core_app(coding_agent_app)) as client:
        due = client.get("/coding-agents/completions/due").json()
    assert due == []
