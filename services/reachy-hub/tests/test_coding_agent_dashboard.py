"""Owner dashboard proxy for coding-agent-service (Phase 29.22), chained
through a real in-process coding-agent-service app with its simulated
provider."""

import asyncio

import httpx
from coding_agent_service.app import create_app as create_coding_agent_app
from reachy_hub.app import create_app as create_hub
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.coding_agent_client import CodingAgentServiceClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

SERVICE_TOKEN = "fixture-coding-agent-token"
CSRF = {"X-Reachy-CSRF": "1"}
PROJECT = {"name": "Demo", "repository_path": "/projects/demo", "provider": "simulated"}


async def _hub():
    app = create_coding_agent_app(service_token=SERVICE_TOKEN)
    users = InMemoryUserStore()
    await users.bootstrap("owner", "password")
    return create_hub(
        user_store=users, session_secret_key="fixture-signing-key", remote_ui_token="fixture-bearer",
        session_store=InMemorySessionStore(), registry=InMemoryRobotRegistry(),
        notification_queue=InMemoryNotificationQueue(), audit_log=InMemoryAuditLog(),
        run_heartbeat_task=False, run_telegram_poll_task=False,
        coding_agent_service_token=SERVICE_TOKEN,
        coding_agent_client=CodingAgentServiceClient(
            "http://coding-agent-service", service_token=SERVICE_TOKEN,
            transport=httpx.ASGITransport(app=app),
        ),
    )


def _client(hub):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=hub), base_url="https://hub.example")


def test_dashboard_requires_owner_login_and_csrf():
    async def run():
        hub = await _hub()
        async with _client(hub) as client:
            assert (await client.get("/coding-agents/sessions")).status_code == 401
            await client.post("/auth/login", headers=CSRF, json={"username": "owner", "password": "password"})
            assert (await client.post("/coding-agents/projects", json=PROJECT)).status_code == 403

    asyncio.run(run())


def test_project_session_lifecycle_through_the_dashboard():
    async def run():
        hub = await _hub()
        async with _client(hub) as client:
            await client.post("/auth/login", headers=CSRF, json={"username": "owner", "password": "password"})
            project = (await client.post("/coding-agents/projects", headers=CSRF, json=PROJECT)).json()
            assert (await client.get("/coding-agents/projects")).json()[0]["id"] == project["id"]

            started = await client.post(
                "/coding-agents/sessions", headers=CSRF,
                json={"project_id": project["id"], "task_summary": "Fix the bug"},
            )
            assert started.status_code == 200
            session = started.json()
            # Never browser-supplied.
            assert session["owner_user_id"] == "default-user"
            assert (await client.get("/coding-agents/sessions")).json()[0]["id"] == session["id"]
            assert (await client.get(f"/coding-agents/sessions/{session['id']}/events")).json()
            assert (await client.get(f"/coding-agents/sessions/{session['id']}/usage")).status_code == 200
            assert (await client.post(f"/coding-agents/sessions/{session['id']}/refresh", headers=CSRF)).status_code == 200
            stopped = await client.post(f"/coding-agents/sessions/{session['id']}/stop", headers=CSRF)
            assert stopped.json()["status"] in ("stopped", "completed")  # the simulated refresh already completed it
            allowance = await client.get("/coding-agents/allowance/simulated")
            assert allowance.json()["provider"] == "simulated"

    asyncio.run(run())


def test_dashboard_surfaces_service_refusals_and_rejects_extra_fields():
    async def run():
        hub = await _hub()
        async with _client(hub) as client:
            await client.post("/auth/login", headers=CSRF, json={"username": "owner", "password": "password"})
            missing = await client.post(
                "/coding-agents/sessions", headers=CSRF, json={"project_id": "nope", "task_summary": "x"}
            )
            assert missing.status_code == 404
            extra = await client.post(
                "/coding-agents/sessions", headers=CSRF,
                json={"project_id": "p", "task_summary": "x", "owner_user_id": "someone-else"},
            )
            assert extra.status_code == 422
            assert (await client.get("/coding-agents/sessions/nope/events")).status_code == 404

    asyncio.run(run())
