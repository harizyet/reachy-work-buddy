"""Owner-facing credential proxy for coding-agent-service (Phase 29.19).
Chained through a real in-process coding-agent-service app via
httpx.ASGITransport, same pattern as test_google_accounts.py's hub->core
chain — coding-agent-service is a sibling workspace member, importable
here only because uv installs every workspace member into one shared dev
venv; production reachy-hub images do not include its code.
"""

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

from shared.protocols import coding_agent as paths

SERVICE_TOKEN = "fixture-coding-agent-token"
CSRF = {"X-Reachy-CSRF": "1"}


async def _chain():
    coding_agent_app = create_coding_agent_app(service_token=SERVICE_TOKEN)
    users = InMemoryUserStore()
    await users.bootstrap("owner", "password")
    hub = create_hub(
        user_store=users, session_secret_key="fixture-signing-key", remote_ui_token="fixture-bearer",
        session_store=InMemorySessionStore(), registry=InMemoryRobotRegistry(),
        notification_queue=InMemoryNotificationQueue(), audit_log=InMemoryAuditLog(),
        run_heartbeat_task=False, run_telegram_poll_task=False,
        coding_agent_service_token=SERVICE_TOKEN,
        coding_agent_client=CodingAgentServiceClient(
            "http://coding-agent-service", service_token=SERVICE_TOKEN,
            transport=httpx.ASGITransport(app=coding_agent_app),
        ),
    )
    return hub


async def _login(client: httpx.AsyncClient) -> None:
    response = await client.post("/auth/login", headers=CSRF, json={"username": "owner", "password": "password"})
    assert response.status_code == 200


def test_requires_login_and_csrf():
    async def run():
        hub = await _chain()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hub), base_url="https://hub.example") as client:
            assert (await client.get(paths.PROVIDER_CREDENTIALS)).status_code == 401
            await _login(client)
            # No CSRF header on a mutating request, even once logged in.
            response = await client.put(
                paths.PROVIDER_CREDENTIAL.format(provider="claude-code"),
                json={"kind": "api_key", "value": "sk-ant-abcd1234"},
            )
            assert response.status_code == 403

    asyncio.run(run())


def test_set_describe_and_clear_credential_never_echoes_the_secret():
    async def run():
        hub = await _chain()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hub), base_url="https://hub.example") as client:
            await _login(client)

            assert (await client.get(paths.PROVIDER_CREDENTIAL.format(provider="claude-code"))).status_code == 404

            set_response = await client.put(
                paths.PROVIDER_CREDENTIAL.format(provider="claude-code"),
                headers=CSRF, json={"kind": "api_key", "value": "sk-ant-abcd1234"},
            )
            assert set_response.status_code == 200
            assert set_response.json()["last_four"] == "1234"
            assert "sk-ant-abcd1234" not in set_response.text

            describe = await client.get(paths.PROVIDER_CREDENTIAL.format(provider="claude-code"))
            assert describe.json()["last_four"] == "1234"

            listing = await client.get(paths.PROVIDER_CREDENTIALS)
            assert [r["provider"] for r in listing.json()] == ["claude-code"]

            clear = await client.delete(paths.PROVIDER_CREDENTIAL.format(provider="claude-code"), headers=CSRF)
            assert clear.status_code == 200
            assert (await client.get(paths.PROVIDER_CREDENTIAL.format(provider="claude-code"))).status_code == 404

    asyncio.run(run())


def test_unknown_provider_is_rejected_before_reaching_coding_agent_service():
    async def run():
        hub = await _chain()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hub), base_url="https://hub.example") as client:
            await _login(client)
            response = await client.put(
                paths.PROVIDER_CREDENTIAL.format(provider="not-a-real-provider"),
                headers=CSRF, json={"kind": "api_key", "value": "x"},
            )
            assert response.status_code == 404

    asyncio.run(run())


def test_disabled_without_a_configured_service_token():
    async def run():
        hub = create_hub(
            user_store=InMemoryUserStore(), session_secret_key="fixture-signing-key",
            remote_ui_token="fixture-bearer", session_store=InMemorySessionStore(),
            registry=InMemoryRobotRegistry(), notification_queue=InMemoryNotificationQueue(),
            audit_log=InMemoryAuditLog(), run_heartbeat_task=False, run_telegram_poll_task=False,
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hub), base_url="https://hub.example") as client:
            assert (await client.get(paths.PROVIDER_CREDENTIALS)).status_code == 503

    asyncio.run(run())
