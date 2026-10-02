"""Phase 29: companion-core's conversation branch answering owner questions
about coding-agent sessions, and the /coding-agents/completions/due route
reachy-hub polls. Chained against a real in-process coding-agent-service
app via httpx.ASGITransport — a sibling workspace member, importable here
only because uv installs every workspace member into one shared dev venv;
production companion-core images do not include its code.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
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

from shared.models.coding_agent import UsageDimension, UsageSnapshot

SERVICE_TOKEN = "fixture-coding-agent-token"


def _coding_agent_app(provider=None):
    return create_coding_agent_app(
        store=InMemoryCodingAgentStore(),
        providers={"simulated": provider or SimulatedProvider()},
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


@pytest.mark.parametrize("question", ["is my coding session done", "Hi are any of my Claude code sessions still running?"])
def test_status_question_reports_a_real_session_without_the_model(question) -> None:
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
        body = _turn(client, question)
    assert "Refactor module X" in body["reply"]
    assert "finished" in body["reply"]
    assert body["privacy"] == "work-private"


def test_status_question_with_no_sessions() -> None:
    with TestClient(_core_app(_coding_agent_app())) as client:
        body = _turn(client, "is my claude session done")
    assert "No coding sessions found" in body["reply"]


@pytest.mark.parametrize("summary", ["ask: pick one", "Completed task"])
def test_usage_question_includes_finished_sessions(summary) -> None:
    coding_agent_app = _coding_agent_app()
    coding_agent_client = TestClient(coding_agent_app)
    headers = {"X-Reachy-Coding-Agent-Service-Token": SERVICE_TOKEN}
    project = coding_agent_client.post(
        "/projects", headers=headers,
        json={"name": "X", "repository_path": "/x", "provider": "simulated"},
    ).json()
    coding_agent_client.post(
        "/sessions", headers=headers,
        json={"project_id": project["id"], "task_summary": summary, "owner_user_id": "owner-1"},
    )

    with TestClient(_core_app(coding_agent_app)) as client:
        body = _turn(client, "What is my Claude code usage so far?")
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


def test_completed_session_usage_is_fetched_from_service():
    class MeasuredProvider(SimulatedProvider):
        async def collect_usage(self, session):
            return UsageSnapshot(
                session_id=session.id, provider="simulated",
                dimensions=[UsageDimension(name="input_tokens", value=1581, unit="tokens")],
            )

    coding_app = _coding_agent_app(MeasuredProvider())
    with TestClient(coding_app) as service:
        headers = {"X-Reachy-Coding-Agent-Service-Token": SERVICE_TOKEN}
        project = service.post("/projects", headers=headers, json={
            "name": "X", "repository_path": "/x", "provider": "simulated",
        }).json()
        session = service.post("/sessions", headers=headers, json={
            "project_id": project["id"], "task_summary": "Finished task", "owner_user_id": "owner-1",
        }).json()
        assert session["status"] == "completed"
        with TestClient(_core_app(coding_app)) as client:
            body = _turn(client, "What is my Claude code usage so far?")
    assert "input tokens 1581tokens" in body["reply"]
    assert "not account-wide" in body["reply"]
    assert body["privacy"] == "work-private"


@pytest.mark.parametrize("command, expected, privacy", [
    ("/coding_sessions", "No coding sessions found", "work-private"),
    ("/coding_usage", "no recorded coding-agent usage", "work-private"),
    ("/today", "nothing on your calendar today", "work-private"),
    ("/next_event", "nothing else on your calendar", "work-private"),
    ("/tasks", "no open tasks", "work-private"),
    ("/find_tasks my tasks", "No tasks found matching 'my tasks'", "work-private"),
    ("/inbox", "inbox is empty", "work-private"),
    ("/recall next meeting", "anything stored about 'next meeting'", "work-private"),
    ("/docs my tasks", "anything in the docs about 'my tasks'", "work-private"),
    ("/time", "It's ", "public"),
    ("/date", "It's ", "public"),
    ("/help", "/coding_usage", "public"),
    ("/docs", "Usage: /docs <topic>", "public"),
    ("/tasks next meeting", "Usage: /tasks", "public"),
    ("/unknown my tasks", "Unknown or unavailable command", "public"),
])
@pytest.mark.parametrize("channel", ["telegram", "web"])
def test_query_commands_bypass_model_and_preserve_privacy(command, expected, privacy, channel):
    with TestClient(_core_app(_coding_agent_app())) as client:
        response = client.post("/conversation", json={
            "session_id": "query", "conversation_id": "query", "channel": channel,
            "input_modality": "text", "text": command, "force_frontier": True,
        })
    assert response.status_code == 200
    assert expected in response.json()["reply"]
    assert response.json()["privacy"] == privacy


def test_usage_reply_includes_account_allowance_reported_by_the_provider():
    resets_at = datetime.now(UTC) + timedelta(hours=2)

    class AllowanceProvider(SimulatedProvider):
        async def collect_usage(self, session):
            return UsageSnapshot(
                session_id=session.id, provider="simulated",
                dimensions=[
                    UsageDimension(name="input_tokens", value=10, unit="tokens"),
                    UsageDimension(name="five_hour_window", value=87.0, unit="%", resets_at=resets_at),
                ],
            )

    coding_app = _coding_agent_app(AllowanceProvider())
    with TestClient(coding_app) as service:
        headers = {"X-Reachy-Coding-Agent-Service-Token": SERVICE_TOKEN}
        project = service.post("/projects", headers=headers, json={
            "name": "X", "repository_path": "/x", "provider": "simulated",
        }).json()
        service.post("/sessions", headers=headers, json={
            "project_id": project["id"], "task_summary": "Finished task", "owner_user_id": "owner-1",
        })
        with TestClient(_core_app(coding_app)) as client:
            body = _turn(client, "What is my Claude code usage so far?")
    assert "Claude 5-hour window: 87% used, resets" in body["reply"]
    assert "input tokens 10tokens" in body["reply"]
    assert "five hour window" not in body["reply"]


def test_usage_reply_survives_an_allowance_endpoint_failure():
    class NoAllowanceApp:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"].endswith("/allowance"):
                scope = {**scope, "path": "/nonexistent"}
            await self.app(scope, receive, send)

    coding_app = _coding_agent_app()
    with TestClient(coding_app) as service:
        headers = {"X-Reachy-Coding-Agent-Service-Token": SERVICE_TOKEN}
        project = service.post("/projects", headers=headers, json={
            "name": "X", "repository_path": "/x", "provider": "simulated",
        }).json()
        service.post("/sessions", headers=headers, json={
            "project_id": project["id"], "task_summary": "Finished task", "owner_user_id": "owner-1",
        })
        with TestClient(_core_app(NoAllowanceApp(coding_app))) as client:
            body = _turn(client, "What is my Claude code usage so far?")
    assert "Finished task" in body["reply"]
    assert "has not reported your allowance" in body["reply"]


def test_status_question_includes_terminal_sessions(tmp_path) -> None:
    folder = tmp_path / "-home-me-proj"
    folder.mkdir()
    (folder / "abc.jsonl").write_text(
        '{"type":"user","cwd":"/home/me/proj","message":{"content":"Tidy the parser"}}\n'
    )
    coding_agent_app = create_coding_agent_app(
        store=InMemoryCodingAgentStore(), providers={"simulated": SimulatedProvider()},
        service_token=SERVICE_TOKEN, terminal_sessions_dir=tmp_path,
    )
    with TestClient(_core_app(coding_agent_app)) as client:
        body = _turn(client, "is my claude session done")
    assert "Tidy the parser (proj)" in body["reply"]
