import asyncio

import httpx
import pytest
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
from reachy_hub.user_store import InMemoryUserStore, hash_password, verify_password

CSRF = {"X-Reachy-CSRF": "1"}


def make_client(**kwargs):
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(),
        run_meeting_worker_task=False,
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
    # A UI deploy must not leave browsers running a stale app.js.
    assert client.get("/ui/app.js").headers["cache-control"] == "no-cache"
    assert client.get("/ui/").headers["cache-control"] == "no-cache"


def test_meetings_proxy_upload_list_get_cancel_require_auth(monkeypatch):
    from starlette.datastructures import UploadFile

    original_read = UploadFile.read

    async def bounded_read(self, size=-1):
        assert size >= 0, "hub/core must not buffer the complete meeting upload"
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", bounded_read)
    client = make_client()
    files = {"audio": ("meeting.wav", b"RIFF....WAVEfmt ", "audio/wav")}

    unauthenticated = client.post("/meetings", data={"title": "Weekly sync"}, files=files)
    assert unauthenticated.status_code == 401

    login(client)
    uploaded = client.post("/meetings", data={"title": "Weekly sync", "participants": "Hariz, Alice"}, files=files, headers=CSRF)
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["title"] == "Weekly sync"
    assert body["participants"] == ["Hariz", "Alice"]
    meeting_id = body["id"]

    assert [m["id"] for m in client.get("/meetings").json()] == [meeting_id]
    assert client.get(f"/meetings/{meeting_id}").json()["id"] == meeting_id
    assert client.get("/meetings/does-not-exist").status_code == 404

    # the recording streams through the hub with byte ranges, behind the same login
    audio = client.get(f"/meetings/{meeting_id}/audio")
    assert audio.status_code == 200 and audio.content == b"RIFF....WAVEfmt " and audio.headers["content-type"] == "audio/wav"
    part = client.get(f"/meetings/{meeting_id}/audio", headers={"Range": "bytes=4-7"})
    assert part.status_code == 206 and part.content == b"...." and part.headers["content-range"] == "bytes 4-7/16"
    assert client.get("/meetings/does-not-exist/audio").status_code == 404
    client.cookies.clear()
    assert client.get(f"/meetings/{meeting_id}/audio").status_code == 401
    login(client)

    # rename and describe go through the hub behind the same login
    assert client.put(f"/meetings/{meeting_id}/title", json={"title": "x"}).status_code == 403   # no CSRF header
    renamed = client.put(f"/meetings/{meeting_id}/title", json={"title": "Weekly review", "description": "Status round."}, headers=CSRF)
    assert renamed.status_code == 200 and renamed.json()["title"] == "Weekly review" and renamed.json()["title_source"] == "owner"
    assert client.put(f"/meetings/{meeting_id}/title", json={}, headers=CSRF).status_code == 422
    assert client.put("/meetings/nope/title", json={"title": "x"}, headers=CSRF).status_code == 404
    assert client.post(f"/meetings/{meeting_id}/describe", headers=CSRF).status_code == 409   # not processed yet

    cancelled = client.post(f"/meetings/{meeting_id}/cancel", headers=CSRF)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(f"/meetings/{meeting_id}/cancel", headers=CSRF).status_code == 409


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


def test_websearch_log_requires_owner_login():
    client = make_client()
    assert client.get("/websearch/log").status_code == 401
    login(client)
    log = client.get("/websearch/log").json()
    assert log["entries"] == [] and log["usage"]["limits"]["brave"] == 900


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


def test_motion_settings_proxy_requires_owner_and_csrf_and_updates_robot():
    from shared.protocols.operator_api import ROBOT_MOTION_SETTINGS

    client = make_client()
    path = ROBOT_MOTION_SETTINGS.format(robot_id="desk")
    settings = {"conversation_motion": True, "speech_wobble": False}
    assert client.get(path).status_code == 401
    assert client.put(path, json=settings).status_code == 401
    login(client)
    client.post("/robots", json={"robot_id": "desk", "base_url": "http://robot"})
    assert client.put(path, json=settings).status_code == 403
    assert client.get(path).json()["conversation_motion"] is False
    response = client.put(path, json=settings, headers=CSRF)
    assert response.status_code == 200
    assert response.json() == {**settings, "conversation_active": False}
    assert client.get(path).json() == response.json()
    assert client.put(path, json={**settings, "speech_wobble": "false"}, headers=CSRF).status_code == 422
    assert client.get(ROBOT_MOTION_SETTINGS.format(robot_id="missing")).status_code == 404
    client.post("/auth/logout", headers=CSRF)
    assert client.get(path, headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_web_chat_archive_auth_roundtrip_and_shared_session():
    client = make_client()
    assert client.get('/chats?user_id=default-user').status_code == 401
    login(client)
    assert client.post('/chats', json={'user_id': 'default-user', 'title': 'First'}).status_code == 403
    records = []
    responses = []
    for title in ['First <script>', 'Second']:
        record = client.post('/chats', json={'user_id': 'default-user', 'title': title}, headers=CSRF).json()
        records.append(record)
        response = client.post('/messages', json={
            'user_id': 'default-user', 'channel': 'web', 'text': 'hello', 'chat_id': record['id'],
        }, headers=CSRF)
        assert response.status_code == 200
        responses.append(response.json())
    assert responses[0]['session_id'] == responses[1]['session_id']
    assert responses[0]['conversation_id'] == responses[1]['conversation_id']
    listing = client.get('/chats?user_id=default-user')
    assert listing.headers['cache-control'] == 'no-store'
    assert len(listing.json()) == 2
    detail = client.get(f"/chats/{records[0]['id']}?user_id=default-user").json()
    assert detail['title'] == 'First <script>'
    assert detail['turns'][0]['text'] == 'hello'
    assert detail['turns'][0]['reply'] == responses[0]['reply']
    assert detail['turns'][0]['status'] == 'complete'
    assert client.get(f"/chats/{records[0]['id']}?user_id=other").status_code == 404
    assert client.post('/messages', json={
        'user_id': 'other', 'channel': 'web', 'text': 'hello', 'chat_id': records[0]['id'],
    }, headers=CSRF).status_code == 404
    assert client.post('/messages', json={
        'user_id': 'default-user', 'channel': 'reachy', 'text': 'hello', 'chat_id': records[0]['id'],
    }, headers=CSRF).status_code == 422
    client.post('/auth/logout', headers=CSRF)
    assert client.get(f"/chats/{records[0]['id']}?user_id=default-user").status_code == 401
    assert client.post('/messages', json={
        'user_id': 'default-user', 'channel': 'web', 'text': 'hello', 'chat_id': records[0]['id'],
    }, headers=CSRF).status_code == 401
    login(client)
    assert len(client.get('/chats?user_id=default-user').json()) == 2


def test_chat_owner_binding_bearer_and_ambiguous_failure():
    async def fail(request):
        raise httpx.ConnectError('fixture unavailable', request=request)

    core = CompanionCoreClient('http://core', transport=httpx.MockTransport(fail))
    client = make_client(accounts_service_token='fixture-service', companion_core_client=core)
    bearer = {'Authorization': 'Bearer test-token'}
    assert client.get('/chats?user_id=other', headers=bearer).status_code == 403
    assert client.post('/chats', json={'user_id': 'other', 'title': 'no'}, headers=bearer).status_code == 403
    record = client.post('/chats', json={'user_id': 'default-user', 'title': 'Failure'}, headers=bearer).json()
    response = client.post('/messages', json={
        'user_id': 'default-user', 'channel': 'web', 'text': 'hello', 'chat_id': record['id'],
    }, headers=bearer)
    assert response.status_code == 502
    detail = client.get(f"/chats/{record['id']}?user_id=default-user", headers=bearer).json()
    assert len(detail['turns']) == 1
    assert detail['turns'][0]['status'] == 'unknown'
    assert detail['turns'][0]['reply'] is None


def test_planner_proxy_requires_auth_and_round_trips_through_core():
    client = make_client()
    assert client.get("/planner/tasks").status_code == 401
    assert client.post("/planner/tasks", json={"text": "x"}, headers=CSRF).status_code == 401
    login(client)
    task = client.post("/planner/tasks", json={"text": "call dentist"}, headers=CSRF).json()
    assert client.get("/planner/tasks").json()[0]["text"] == "call dentist"
    assert client.post(f"/planner/tasks/{task['id']}/complete", headers=CSRF).json()["status"] == "done"
    assert client.put("/planner/tasks/missing", json={"text": "y"}, headers=CSRF).status_code == 404
    assert client.post("/planner/tasks", json={"text": ""}, headers=CSRF).status_code == 422

    note = client.post("/planner/notes", json={"title": "N", "body": "<b>x</b>"}, headers=CSRF).json()
    assert client.get("/planner/notes", params={"q": "<b>"}).json()[0]["id"] == note["id"]
    assert client.delete(f"/planner/notes/{note['id']}", headers=CSRF).json() == {"deleted": True}

    reminder = client.post(
        "/planner/reminders", json={"text": "r", "due_at": "2020-01-01T00:00:00Z"}, headers=CSRF
    ).json()
    assert client.get("/planner/reminders").json()[0]["id"] == reminder["id"]
    assert client.post(f"/planner/reminders/{reminder['id']}/complete", headers=CSRF).json()["status"] == "done"


def test_alarm_and_station_proxy_requires_auth_and_round_trips_through_core():
    def tunein(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("Search.ashx")
        return httpx.Response(
            200, json={"body": [{"guide_id": "s24896", "text": "Test FM", "subtext": "jazz"}, {"guide_id": "p1", "text": "x"}]}
        )

    client = make_client(tunein_transport=httpx.MockTransport(tunein))
    assert client.get("/planner/alarms").status_code == 401
    assert client.post("/planner/alarms", json={"label": "x", "due_at": "2030-01-01T00:00:00Z"}, headers=CSRF).status_code == 401
    assert client.post("/planner/alarms/stop", headers=CSRF).status_code == 401
    assert client.patch("/planner/alarms/x", json={"enabled": False}, headers=CSRF).status_code == 401
    assert client.get("/planner/receipts").status_code == 401
    assert client.get("/planner/stations/search", params={"q": "jazz"}).status_code == 401
    login(client)

    found = client.get("/planner/stations/search", params={"q": "jazz"}).json()
    assert found == [{"guide_id": "s24896", "name": "Test FM", "detail": "jazz"}]
    assert client.get("/planner/stations/search", params={"q": "j"}).status_code == 422

    assert client.post("/planner/stations", json={"name": "Test FM", "guide_id": "http://evil"}, headers=CSRF).status_code == 422
    station = client.post("/planner/stations", json={"name": "Test FM", "guide_id": "s24896"}, headers=CSRF).json()
    assert client.get("/planner/stations").json()[0]["id"] == station["id"]

    alarm = client.post(
        "/planner/alarms",
        json={"label": "wake", "due_at": "2030-01-01T07:00:00Z", "station_id": station["id"], "volume": 250},
        headers=CSRF,
    ).json()
    assert alarm["station_id"] == station["id"] and alarm["status"] == "scheduled"
    assert alarm["volume"] == 250
    assert client.post("/planner/alarms", json={"label": "x", "due_at": "2030-01-01T07:00:00"}, headers=CSRF).status_code == 422
    assert client.get("/planner/alarms").json()[0]["id"] == alarm["id"]
    assert client.post("/planner/alarms/stop", headers=CSRF).json() == {"stopped": False}
    # the clock screen: a repeating alarm by time of day, edited and switched off through the proxy
    daily = client.post("/planner/alarms", json={"label": "Gym", "time": "06:30", "repeat": [0, 2, 4]}, headers=CSRF).json()
    assert daily["repeat"] == [0, 2, 4] and daily["enabled"] is True
    off = client.patch(f"/planner/alarms/{daily['id']}", json={"enabled": False}, headers=CSRF).json()
    assert off["enabled"] is False and off["label"] == "Gym"
    edited = client.patch(f"/planner/alarms/{daily['id']}", json={"label": "Run", "station_id": None, "repeat": []}, headers=CSRF).json()
    assert edited["label"] == "Run" and edited["repeat"] == [] and edited["station_id"] is None
    assert client.patch("/planner/alarms/missing", json={"enabled": True}, headers=CSRF).status_code == 404
    assert client.patch(f"/planner/alarms/{daily['id']}", json={"time": "25:00"}, headers=CSRF).status_code == 422
    assert client.delete(f"/planner/alarms/{alarm['id']}", headers=CSRF).json()["status"] == "cancelled"
    assert client.delete("/planner/alarms/missing", headers=CSRF).status_code == 404
    assert client.delete(f"/planner/stations/{station['id']}", headers=CSRF).json() == {"deleted": True}


def test_meeting_speaker_and_correction_proxies_need_auth_and_pass_core_errors_through():
    client = make_client()
    files = {"audio": ("meeting.wav", b"RIFF....WAVEfmt ", "audio/wav")}
    assert client.put("/meetings/x/speakers", json={"names": {}}, headers=CSRF).status_code == 401
    assert client.post("/meetings/x/corrections/suggest", headers=CSRF).status_code == 401
    assert client.put("/meetings/x/corrections/0", json={"text": "t"}, headers=CSRF).status_code == 401
    assert client.delete("/meetings/x/corrections/0", headers=CSRF).status_code == 401
    assert client.post("/meetings/x/corrections/replace", json={"find": "a", "replace": "b"}, headers=CSRF).status_code == 401
    assert client.get("/meeting-terms").status_code == 401
    assert client.delete("/meetings/x", headers=CSRF).status_code == 401
    assert client.post("/meetings/x/outputs/summary", headers=CSRF).status_code == 401
    assert client.delete("/meetings/x/outputs/summary", headers=CSRF).status_code == 401
    assert client.post("/meetings/x/outputs/summary/deep", headers=CSRF).status_code == 401
    assert client.get("/deep-review/info").status_code == 401
    assert client.get("/deep-review/current").status_code == 401
    assert client.get("/deep-review/x").status_code == 401
    assert client.post("/meetings/x/corrections/deep-review", headers=CSRF).status_code == 401
    assert client.put("/meetings/x/terms", json={"terms": []}, headers=CSRF).status_code == 401

    login(client)
    meeting_id = client.post("/meetings", data={"title": "Sync"}, files=files, headers=CSRF).json()["id"]
    # No transcript or diarization yet: core's 4xx reaches the owner instead of a 502.
    assert client.put(f"/meetings/{meeting_id}/speakers", json={"names": {"SPEAKER_00": "Ana"}}, headers=CSRF).status_code == 422
    assert client.post(f"/meetings/{meeting_id}/corrections/suggest", headers=CSRF).status_code == 409
    assert client.put(f"/meetings/{meeting_id}/corrections/0", json={"text": "t"}, headers=CSRF).status_code == 404
    assert client.put(f"/meetings/{meeting_id}/corrections/0", json={"text": ""}, headers=CSRF).status_code == 422
    assert client.post(f"/meetings/{meeting_id}/corrections/replace", json={"find": "a", "replace": "b"}, headers=CSRF).status_code == 409
    # Phase 43: outputs need a processed transcript (409 passes through), unknown kinds are 422, delete works.
    assert client.post(f"/meetings/{meeting_id}/outputs/summary", headers=CSRF).status_code == 409
    assert client.post(f"/meetings/{meeting_id}/outputs/summary/deep", headers=CSRF).status_code == 409
    assert client.delete(f"/meetings/{meeting_id}/outputs/poem", headers=CSRF).status_code == 422
    assert client.delete(f"/meetings/{meeting_id}", headers=CSRF).status_code == 409  # still queued: cancel first
    assert client.post(f"/meetings/{meeting_id}/cancel", headers=CSRF).status_code == 200
    # Deep local review: with no model manager configured, core's refusal reaches the owner as a 409, not a 502.
    assert client.get("/deep-review/info").json()["configured"] is False
    assert client.get("/deep-review/current").json() is None
    assert client.get("/deep-review/nope").status_code == 404
    assert client.post(f"/meetings/{meeting_id}/corrections/deep-review", headers=CSRF).status_code == 409
    assert client.put(f"/meetings/{meeting_id}/terms", json={"terms": ["Gemini"]}, headers=CSRF).json()["key_terms"] == ["Gemini"]
    assert client.post("/meeting-terms", json={"term": "Codex"}, headers=CSRF).json() == ["Codex"]
    assert client.get("/meeting-terms").json() == ["Codex"]
    assert client.delete("/meeting-terms", params={"term": "codex"}, headers=CSRF).json() == []
    assert client.post("/meeting-terms", json={"term": ""}, headers=CSRF).status_code == 422
    assert client.put("/meetings/missing/speakers", json={"names": {}}, headers=CSRF).status_code == 404


class _RecordingVoice:
    def __init__(self):
        self.said = []

    def synthesize(self, text):
        self.said.append(text)
        return b"RIFF-wav"


def test_speech_returns_reachys_voice_for_the_owner_only_and_strips_markup():
    voice = _RecordingVoice()
    client = make_client(tts=voice)
    assert client.post("/speech", json={"text": "hello"}, headers=CSRF).status_code == 401
    login(client)
    assert client.post("/speech", json={"text": "hello"}).status_code in (401, 403)  # no CSRF header
    ok = client.post("/speech", json={"text": "**Gemini** is open [S1]"}, headers=CSRF)
    assert ok.status_code == 200 and ok.content == b"RIFF-wav" and ok.headers["content-type"] == "audio/wav"
    assert voice.said == ["Gemini is open"]  # the same cleaning the robot's replies get
    assert client.post("/speech", json={"text": ""}, headers=CSRF).status_code == 422
    assert client.post("/speech", json={"text": "x" * 3001}, headers=CSRF).status_code == 422


def test_a_saved_chat_can_be_deleted_by_its_owner_only():
    client = make_client()
    assert client.delete('/chats/x?user_id=default-user').status_code in (401, 403)
    login(client)
    keep = client.post('/chats', json={'user_id': 'default-user', 'title': 'Keep'}, headers=CSRF).json()
    gone = client.post('/chats', json={'user_id': 'default-user', 'title': 'Delete me'}, headers=CSRF).json()
    client.post('/messages', json={'user_id': 'default-user', 'channel': 'web', 'text': 'hello', 'chat_id': gone['id']}, headers=CSRF)
    assert client.delete(f"/chats/{gone['id']}?user_id=default-user").status_code == 403    # no CSRF header
    assert client.delete(f"/chats/{gone['id']}?user_id=other", headers=CSRF).status_code == 404   # not someone else's
    assert client.delete(f"/chats/{gone['id']}?user_id=default-user", headers=CSRF).json() == {'deleted': True}
    assert client.delete(f"/chats/{gone['id']}?user_id=default-user", headers=CSRF).status_code == 404
    assert [c['id'] for c in client.get('/chats?user_id=default-user').json()] == [keep['id']]
    assert client.get(f"/chats/{gone['id']}?user_id=default-user").status_code == 404


def test_classification_is_forwarded_on_create_and_refused_on_edit():
    """Phase 44A: the hub neither discards the classification nor lets an edit change it silently."""
    client = make_client()
    login(client)
    task = client.post(
        "/planner/tasks", json={"text": "t", "sensitivity": "sensitive", "project_scope": "alpha"}, headers=CSRF
    ).json()
    assert (task["sensitivity"], task["project_scope"]) == ("sensitive", "alpha")
    assert client.post("/planner/tasks", json={"text": "plain"}, headers=CSRF).json()["sensitivity"] == "work-private"
    assert client.post("/planner/tasks", json={"text": "bad", "sensitivity": "secret"}, headers=CSRF).status_code == 422

    note = client.post(
        "/planner/notes", json={"title": "N", "sensitivity": "public", "project_scope": "beta"}, headers=CSRF
    ).json()
    assert (note["sensitivity"], note["project_scope"]) == ("public", "beta")
    edited = client.put(f"/planner/notes/{note['id']}", json={"title": "N2"}, headers=CSRF).json()
    assert (edited["sensitivity"], edited["project_scope"]) == ("public", "beta")

    reminder = client.post(
        "/planner/reminders", json={"text": "r", "due_at": "2030-01-01T00:00:00Z", "sensitivity": "sensitive"}, headers=CSRF
    ).json()
    assert reminder["sensitivity"] == "sensitive"

    # An edit that tries to reclassify is a 422, not a silent no-op.
    assert client.put(f"/planner/notes/{note['id']}", json={"title": "N3", "sensitivity": "public"}, headers=CSRF).status_code == 422
    assert client.put(f"/planner/tasks/{task['id']}", json={"text": "t2", "project_scope": "x"}, headers=CSRF).status_code == 422
    assert client.get("/planner/notes").json()[0]["title"] == "N2"

    files = {"audio": ("meeting.wav", b"RIFFxxxx", "audio/wav")}
    meeting = client.post("/meetings", data={"title": "Sync", "sensitivity": "sensitive"}, files=files, headers=CSRF).json()
    assert meeting["sensitivity"] == "sensitive" and meeting["project_scope"] is None
    plain = client.post("/meetings", data={"title": "Sync 2"}, files=files, headers=CSRF).json()
    assert plain["sensitivity"] == "work-private" and plain["project_scope"] is None
    assert client.post("/meetings", data={"title": "x", "sensitivity": "secret"}, files=files, headers=CSRF).status_code == 422


def test_documents_are_core_only_by_design():
    """Documents are ingested through core's operator/setup API only; the hub exposes no route, so there is nothing to forward."""
    client = make_client()
    paths = client.app.openapi()["paths"]
    assert not [p for p in paths if "document" in p]
