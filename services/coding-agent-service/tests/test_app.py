"""HTTP-level tests for coding-agent-service's FastAPI app: route wiring,
the service-token gate, and request validation — the state-machine logic
itself is covered directly in test_service.py."""

import asyncio

from coding_agent_service.app import create_app
from coding_agent_service.claude_provider import ClaudeCodeProvider
from coding_agent_service.credentials import InMemoryCredentialStore
from coding_agent_service.providers import SimulatedProvider
from coding_agent_service.runtime import SimulatedContainerRuntime
from coding_agent_service.store import InMemoryCodingAgentStore
from fastapi.testclient import TestClient

from shared.models.coding_agent import CredentialKind
from shared.protocols import coding_agent as paths

SERVICE_TOKEN = "fixture-service-token"


def _client() -> TestClient:
    app = create_app(
        store=InMemoryCodingAgentStore(),
        providers={"simulated": SimulatedProvider()},
        service_token=SERVICE_TOKEN,
    )
    return TestClient(app)


def _headers() -> dict:
    return {paths.SERVICE_HEADER: SERVICE_TOKEN}


def test_health_does_not_require_service_token() -> None:
    client = _client()
    response = client.get("/health")
    assert response.status_code == 200


def test_routes_reject_missing_or_wrong_service_token() -> None:
    client = _client()
    assert client.get(paths.PROJECTS).status_code == 401
    assert client.get(paths.PROJECTS, headers={paths.SERVICE_HEADER: "wrong"}).status_code == 401


def test_create_project_start_session_and_resume_over_http() -> None:
    client = _client()
    headers = _headers()

    create_response = client.post(
        paths.PROJECTS,
        headers=headers,
        json={"name": "Reachy Work Buddy", "repository_path": "/projects/reachy-work-buddy", "provider": "simulated"},
    )
    assert create_response.status_code == 200
    project = create_response.json()

    start_response = client.post(
        paths.SESSIONS,
        headers=headers,
        json={
            "project_id": project["id"],
            "task_summary": "ask: which migration strategy should I use?",
            "owner_user_id": "owner-1",
        },
    )
    assert start_response.status_code == 200
    session = start_response.json()
    assert session["status"] == "waiting_for_input"

    resume_response = client.post(
        paths.SESSION_RESUME.format(session_id=session["id"]),
        headers=headers,
        json={"instruction": "Use a new migration."},
    )
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "completed"

    events_response = client.get(paths.SESSION_EVENTS.format(session_id=session["id"]), headers=headers)
    assert events_response.status_code == 200
    assert len(events_response.json()) >= 2


def test_start_session_for_unknown_project_returns_404() -> None:
    client = _client()
    response = client.post(
        paths.SESSIONS,
        headers=_headers(),
        json={"project_id": "missing", "task_summary": "x", "owner_user_id": "owner-1"},
    )
    assert response.status_code == 404


def test_resume_a_running_session_returns_409() -> None:
    client = _client()
    headers = _headers()
    project = client.post(
        paths.PROJECTS,
        headers=headers,
        json={"name": "X", "repository_path": "/x", "provider": "simulated"},
    ).json()
    session = client.post(
        paths.SESSIONS,
        headers=headers,
        json={"project_id": project["id"], "task_summary": "quick task", "owner_user_id": "owner-1"},
    ).json()
    assert session["status"] == "completed"

    response = client.post(
        paths.SESSION_RESUME.format(session_id=session["id"]),
        headers=headers,
        json={"instruction": "keep going"},
    )
    assert response.status_code == 409


def test_credential_set_describe_and_clear_never_echo_the_secret() -> None:
    client = _client()
    headers = _headers()

    assert client.get(paths.PROVIDER_CREDENTIAL.format(provider="claude-code"), headers=headers).status_code == 404

    set_response = client.put(
        paths.PROVIDER_CREDENTIAL.format(provider="claude-code"),
        headers=headers,
        json={"kind": "api_key", "value": "sk-ant-abcd1234"},
    )
    assert set_response.status_code == 200
    body = set_response.json()
    assert body["last_four"] == "1234"
    assert "sk-ant-abcd1234" not in set_response.text

    describe_response = client.get(paths.PROVIDER_CREDENTIAL.format(provider="claude-code"), headers=headers)
    assert describe_response.status_code == 200
    assert describe_response.json()["last_four"] == "1234"

    list_response = client.get(paths.PROVIDER_CREDENTIALS, headers=headers)
    assert list_response.status_code == 200
    assert [r["provider"] for r in list_response.json()] == ["claude-code"]

    delete_response = client.delete(paths.PROVIDER_CREDENTIAL.format(provider="claude-code"), headers=headers)
    assert delete_response.status_code == 200
    assert client.get(paths.PROVIDER_CREDENTIAL.format(provider="claude-code"), headers=headers).status_code == 404


def test_refresh_session_calls_the_provider_and_returns_the_updated_session() -> None:
    client = _client()
    headers = _headers()
    project = client.post(
        paths.PROJECTS, headers=headers,
        json={"name": "X", "repository_path": "/x", "provider": "simulated"},
    ).json()
    session = client.post(
        paths.SESSIONS, headers=headers,
        json={"project_id": project["id"], "task_summary": "ask: pick one", "owner_user_id": "owner-1"},
    ).json()
    assert session["status"] == "waiting_for_input"

    refreshed = client.post(paths.SESSION_REFRESH.format(session_id=session["id"]), headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "waiting_for_input"

    assert client.post(paths.SESSION_REFRESH.format(session_id="missing"), headers=headers).status_code == 404


def test_credential_routes_require_service_token() -> None:
    client = _client()
    assert client.get(paths.PROVIDER_CREDENTIALS).status_code == 401
    assert client.put(
        paths.PROVIDER_CREDENTIAL.format(provider="claude-code"), json={"kind": "api_key", "value": "x"}
    ).status_code == 401


def test_starting_a_claude_code_session_with_an_oauth_credential_returns_403() -> None:
    """29.3 hard guardrail (owner request, 2026-10-01), confirmed at the
    HTTP layer: ProviderInvocationBlockedError maps to 403, distinct from
    the generic 409 a plain ProviderError gets."""

    store = InMemoryCodingAgentStore()
    credentials = InMemoryCredentialStore()
    asyncio.run(credentials.set_credential("claude-code", CredentialKind.OAUTH_TOKEN, "sk-ant-oat01-fixture"))
    app = create_app(
        store=store,
        providers={"claude-code": ClaudeCodeProvider(SimulatedContainerRuntime(), credentials, store)},
        service_token=SERVICE_TOKEN,
        credential_store=credentials,
    )
    client = TestClient(app)
    headers = _headers()

    project = client.post(
        paths.PROJECTS, headers=headers,
        json={"name": "X", "repository_path": "/x", "provider": "claude-code"},
    ).json()
    response = client.post(
        paths.SESSIONS, headers=headers,
        json={"project_id": project["id"], "task_summary": "say hi", "owner_user_id": "owner-1"},
    )
    assert response.status_code == 403
