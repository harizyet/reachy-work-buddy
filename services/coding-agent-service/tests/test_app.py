"""HTTP-level tests for coding-agent-service's FastAPI app: route wiring,
the service-token gate, and request validation — the state-machine logic
itself is covered directly in test_service.py."""

from coding_agent_service.app import create_app
from coding_agent_service.providers import SimulatedProvider
from coding_agent_service.store import InMemoryCodingAgentStore
from fastapi.testclient import TestClient

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
