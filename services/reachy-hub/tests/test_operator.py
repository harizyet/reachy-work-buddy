import asyncio

import httpx
import pytest
from companion_core.app import create_app as create_core_app
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
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
        llm_transport=kwargs.pop("llm_transport", None),
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


def test_websearch_settings_proxy_masks_key_and_redacts_validation_errors():
    client = make_client()
    login(client)
    response = client.put(
        "/settings/websearch",
        json={"policy": "auto", "base_url": "http://searxng.local", "api_key": "secret-98765"},
        headers=CSRF,
    )
    assert response.status_code == 200 and "secret-98765" not in response.text
    assert client.get("/settings/websearch").json()["api_key"].endswith("8765")
    bad = client.put("/settings/websearch", json={"api_key": ["do-not-echo"]}, headers=CSRF)
    assert bad.status_code == 422 and "do-not-echo" not in bad.text


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


def test_status_exposes_poll_health_and_configured_default_user():
    from datetime import UTC, datetime, timedelta

    from reachy_hub.telegram_client import TelegramClient

    telegram = TelegramClient('not-a-real-token', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'ok': True, 'result': []})
    ))
    client = make_client(telegram_client=telegram, telegram_default_user_id='configured-owner')
    login(client)
    status = client.get('/status').json()
    assert status['default_user_id'] == 'configured-owner'
    assert status['telegram'] == {
        'configured': True, 'last_poll_at': None, 'last_poll_error': None, 'healthy': False,
    }
    health = client.app.state.telegram_poll_health
    health.last_poll_at = datetime.now(UTC)
    assert client.get('/status').json()['telegram']['healthy']
    health.last_poll_error = 'Telegram polling request failed'
    assert not client.get('/status').json()['telegram']['healthy']
    assert client.post('/messages', json={'user_id': 'configured-owner', 'channel': 'web', 'text': 'Hello'}).status_code == 200
    health.last_poll_error = None
    health.last_poll_at -= timedelta(seconds=61)
    assert not client.get('/status').json()['telegram']['healthy']
    asyncio.run(telegram.aclose())


def test_web_chat_continues_the_same_session_and_keeps_direct_replies():
    client = make_client()
    login(client)
    web = client.post('/messages', json={'user_id': 'same-user', 'channel': 'web', 'text': 'Hello'}).json()
    assert web['active_channel'] == 'web' and web['delivery_channel'] == 'reachy'
    assert web['reply']  # Desk routing must never hide the synchronous web reply.
    client.patch('/sessions/same-user/mode', json={'interaction_mode': 'office'}, headers=CSRF)
    client.patch('/sessions/same-user/dnd', json={'dnd': True}, headers=CSRF)
    telegram = client.post('/messages', json={
        'user_id': 'same-user', 'channel': 'telegram', 'text': 'My salary is private',
    }).json()
    back = client.post('/messages', json={
        'user_id': 'same-user', 'channel': 'web', 'text': 'My salary is private',
    }).json()
    assert web['session_id'] == telegram['session_id'] == back['session_id']
    assert web['conversation_id'] == telegram['conversation_id'] == back['conversation_id']
    assert back['reply'] and back['privacy'] == 'sensitive' and back['delivery_channel'] == 'phone'
    session = client.get('/sessions/same-user').json()
    assert session['active_channel'] == 'web' and session['dnd'] and session['interaction_mode'] == 'office'
    assert len(client.get('/audit/same-user').json()) == 3
    # Page login is not an API authentication retrofit (ADR 0017).
    client.post('/auth/logout', headers=CSRF)
    assert client.post('/messages', json={'user_id': 'other', 'channel': 'web', 'text': 'Hello'}).status_code == 200


def test_web_frontier_override_reaches_core_and_cloud_usage():
    seen = []

    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Cloud answer"}}]}
        )

    client = make_client(llm_transport=httpx.MockTransport(respond))
    login(client)
    result = client.put(
        "/settings/llm",
        headers=CSRF,
        json={
            "local": {"base_url": "http://local", "model": "l"},
            "cloud": {"base_url": "http://cloud", "model": "c"},
            "routing": {"mode": "local_only"},
        },
    )
    assert result.status_code == 200
    reply = client.post(
        "/messages",
        json={
            "user_id": "owner",
            "channel": "web",
            "text": "Hello",
            "force_frontier": True,
        },
    )
    assert reply.json()["reply"] == "Cloud answer"
    assert seen == ["cloud"]
    usage = client.get("/llm/usage").json()
    assert usage["by_role"]["cloud"]["calls"] == 1
    assert usage["latest_escalation"]["reason"] == "manual"
    assert client.get("/status").json()["llm"]["configured"]
