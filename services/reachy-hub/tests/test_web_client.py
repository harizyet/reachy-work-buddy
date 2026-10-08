"""Phase 47A: the React client's contract with the hub, and its static mount.

`clients/web/src/api/` holds a snapshot of the hub's OpenAPI document and sample
responses taken from a real hub app. The operator routes return bare dicts, so
the OpenAPI schema says nothing about their fields; the samples are what the
TypeScript types are written and tested against. These tests fail when a
response changes shape without the snapshot (and so the client types) being
regenerated:

    python services/reachy-hub/tests/test_web_client.py
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from companion_core.app import create_app as create_core_app
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
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

CSRF = {"X-Reachy-CSRF": "1"}
ROOT = Path(__file__).resolve().parents[3]
API_DIR = ROOT / "clients" / "web" / "src" / "api"
# Operations the 47A client calls. Anything else is not part of this contract.
OPERATIONS = [("get", "/auth/me"), ("post", "/auth/login"), ("post", "/auth/logout"), ("get", "/status")]


def make_client() -> TestClient:
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
    )
    embodiment = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    return TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False,
        session_secret_key="test-session-secret", remote_ui_token="test-token",
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)),
        client_factory=lambda url: EmbodimentClient(url, transport=httpx.ASGITransport(app=embodiment)),
    ))


def logged_in_client() -> TestClient:
    client = make_client()
    response = client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF)
    assert response.status_code == 200
    client.post("/robots", json={"robot_id": "desk", "base_url": "http://robot"})
    # Give the LLM usage list one entry's worth of shape: an empty list proves nothing about its items.
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}}, headers=CSRF)
    return client


def shape(value):
    """Keys and JSON types, not values. A list is described by its first item (or `[]`)."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__


def snapshot(client: TestClient) -> dict:
    return {"auth_me": client.get("/auth/me").json(), "status": client.get("/status").json()}


def committed(name: str):
    return json.loads((API_DIR / name).read_text())


def test_sample_responses_still_match_the_hub():
    live = snapshot(logged_in_client())
    saved = committed("samples.json")
    assert shape(live["auth_me"]) == shape(saved["auth_me"])
    # `last_poll_at`/`last_poll_error` are null when Telegram is off and a string otherwise; the client types both.
    for sample in (live, saved):
        sample["status"]["telegram"].pop("last_poll_at"), sample["status"]["telegram"].pop("last_poll_error")
        for robot in sample["status"]["robots"]:
            robot.pop("data", None)  # embodiment state is the robot's own contract, typed loosely on purpose
    assert shape(live["status"]) == shape(saved["status"])


def test_openapi_snapshot_covers_the_client_operations():
    paths = make_client().app.openapi()["paths"]
    saved = committed("openapi.json")["paths"]
    for method, path in OPERATIONS:
        assert path in paths and method in paths[path], (method, path)
        assert paths[path][method] == saved[path][method], f"openapi changed for {method.upper()} {path}; regenerate"


def test_unauthenticated_requests_are_refused_for_the_client_routes():
    client = make_client()
    assert client.get("/auth/me").status_code == 401
    assert client.get("/status").status_code == 401
    # Mutations need the CSRF header the client always sends.
    assert client.post("/auth/logout").status_code == 403


def test_web_mount_serves_beside_the_legacy_clients():
    dist = ROOT / "clients" / "web" / "dist"
    created = not dist.exists()
    if created:
        dist.mkdir()
        (dist / "index.html").write_text('<!doctype html><div id="root"></div>')
    try:
        # Mounts are decided at construction, so the client is built after the directory exists.
        client = make_client()
        assert client.get("/web", follow_redirects=False).headers["location"] == "web/"
        page = client.get("/web/")
        # Either the stub above or a real `npm run build`; both have the React root element.
        assert page.status_code == 200 and 'id="root"' in page.text
        assert page.headers["cache-control"] == "no-cache"
        assert client.get("/ui/").status_code == 200
        assert client.get("/app/").status_code == 200
        assert client.get("/ui/app.js").status_code == 200
    finally:
        if created:
            (dist / "index.html").unlink()
            dist.rmdir()


def regenerate() -> None:
    client = logged_in_client()
    merged: dict = {}
    for method, path in OPERATIONS:
        merged.setdefault(path, {})[method] = client.app.openapi()["paths"][path][method]
    API_DIR.mkdir(parents=True, exist_ok=True)
    document = {"openapi": client.app.openapi()["openapi"], "info": {"title": "reachy-hub (47A client subset)", "version": "snapshot"}, "paths": merged}
    (API_DIR / "openapi.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    (API_DIR / "samples.json").write_text(json.dumps(snapshot(client), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    sys.exit(regenerate())
