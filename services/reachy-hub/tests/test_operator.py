import asyncio

import httpx
import pytest
from companion_core.app import create_app as create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
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
from reachy_hub.user_store import InMemoryUserStore, hash_password, verify_password

CSRF = {"X-Reachy-CSRF": "1"}


def make_client(**kwargs):
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        run_email_dispatch_task=False,
    )
    embodiment = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    kwargs.setdefault("session_secret_key", "test-session-secret")
    kwargs.setdefault("remote_ui_token", "test-token")
    kwargs.setdefault(
        "companion_core_client",
        CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)),
    )
    return TestClient(
        create_app(
            user_store=users,
            registry=InMemoryRobotRegistry(),
            session_store=InMemorySessionStore(),
            audit_log=InMemoryAuditLog(),
            notification_queue=InMemoryNotificationQueue(),
            run_heartbeat_task=False,
            run_telegram_poll_task=False,
            client_factory=lambda url: EmbodimentClient(
                url, transport=httpx.ASGITransport(app=embodiment)
            ),
            **kwargs,
        )
    )


def login(client):
    return client.post(
        "/auth/login",
        json={"username": "owner", "password": "correct-password"},
        headers=CSRF,
    )


def test_password_hashes_are_salted_and_bootstrap_never_overwrites_owner():
    first, second = hash_password("password"), hash_password("password")
    assert first != second and "password" not in first
    assert verify_password("password", first) and not verify_password("wrong", first)

    async def run():
        store = InMemoryUserStore()
        await store.bootstrap("one", "pass")
        await store.bootstrap("two", "new")
        assert await store.owner() == "one"
        assert await store.authenticate("one", "pass")
        assert not await store.authenticate("two", "new")

    asyncio.run(run())


def test_cookie_login_logout_csrf_and_tampering():
    client = make_client(remote_ui_token="")
    assert client.get("/auth/me").status_code == 401
    assert client.get("/status").status_code == 401
    assert (
        client.post(
            "/auth/login", json={"username": "owner", "password": "wrong"}, headers=CSRF
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"username": "owner", "password": "correct-password"}
        ).status_code
        == 403
    )
    result = login(client)
    assert result.status_code == 200
    assert "httponly" in result.headers["set-cookie"].lower()
    assert "samesite=strict" in result.headers["set-cookie"].lower()
    assert client.get("/auth/me").json() == {"username": "owner"}
    assert client.get("/status").status_code == 200
    assert client.put("/settings/llm", json={}).status_code == 403
    assert client.put("/settings/llm", json={}, headers=CSRF).status_code == 200
    assert client.post("/auth/logout", headers=CSRF).status_code == 200
    assert client.get("/status").status_code == 401
    client.cookies.set("reachy_session", "forged-cookie")
    assert client.get("/status").status_code == 401


@pytest.mark.parametrize(
    "path,body",
    [
        ("/sessions/user/mode", {"interaction_mode": "silent"}),
        ("/sessions/user/dnd", {"dnd": True}),
        ("/sessions/user/privacy-context", {"privacy_context": "meeting"}),
    ],
)
def test_session_mutations_require_auth_and_accept_both_mechanisms(path, body):
    client = make_client()
    assert (
        client.post(
            "/messages", json={"user_id": "user", "channel": "web", "text": "hello"}
        ).status_code
        == 200
    )
    assert client.patch(path, json=body).status_code == 401
    assert (
        client.patch(
            path, json=body, headers={"Authorization": "Bearer test-token"}
        ).status_code
        == 200
    )
    login(client)
    assert client.patch(path, json=body, headers=CSRF).status_code == 200
    assert (
        client.patch(
            path, json=body, headers={**CSRF, "Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )


def test_proxy_masked_settings_and_status_real_chain():
    client = make_client()
    login(client)
    client.post("/robots", json={"robot_id": "desk", "base_url": "http://robot"})
    response = client.put(
        "/settings/llm",
        json={
            "local": {
                "base_url": "http://ovms/v1",
                "model": "qwen",
                "api_key": "secret-12345",
            }
        },
        headers=CSRF,
    )
    assert response.status_code == 200 and "secret-12345" not in response.text
    assert client.get("/settings/llm").json()["local"]["api_key"].endswith("2345")
    status = client.get("/status").json()
    assert status["companion_core"]["status"] == "ok"
    assert status["robots"][0]["status"] == "ok"
    assert status["llm"]["configured"]
    assert not status["telegram"]["configured"]
    assert client.get("/llm/usage").json()["summary"]["calls"] == 0
    assert client.get("/ui/").status_code == 200
    assert client.get("/ui/app.js").status_code == 200


def test_status_handles_down_core_without_hiding_hub():
    def down(request):
        raise httpx.ConnectError("private connection details", request=request)

    client = make_client(
        companion_core_client=CompanionCoreClient(
            "http://core", transport=httpx.MockTransport(down)
        )
    )
    login(client)
    result = client.get("/status")
    assert result.status_code == 200 and "private connection details" not in result.text
    assert result.json()["companion_core"]["status"] == "unavailable"
    assert result.json()["reachy_hub"]["status"] == "ok"
    assert result.json()["llm"]["configured"] is None
    assert client.get("/settings/llm").status_code == 502


def test_secure_cookie_setting():
    client = make_client(session_cookie_secure=True)
    assert "secure" in login(client).headers["set-cookie"].lower()


def test_credential_validation_is_redacted_and_ui_redirect_is_relative():
    client = make_client()
    response = client.post(
        "/auth/login",
        json={"username": "owner", "password": ["do-not-echo"]},
        headers=CSRF,
    )
    assert response.status_code == 422 and "do-not-echo" not in response.text
    login(client)
    response = client.put(
        "/settings/llm", json={"local": {"api_key": ["do-not-echo"]}}, headers=CSRF
    )
    assert response.status_code == 422 and "do-not-echo" not in response.text
    response = client.get("/ui", follow_redirects=False)
    assert response.headers["location"] == "ui/"
