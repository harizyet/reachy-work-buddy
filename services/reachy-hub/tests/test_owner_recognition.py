"""Phase 25a.2/25b.3 owner-recognition enrollment capture portal skeleton
(docs/phase-25.md, reachy_hub/owner_recognition.py). Raw sample capture
only -- no biometric template/model exists yet."""

import asyncio

from fastapi.testclient import TestClient
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.enrollment_store import InMemoryEnrollmentStore
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

CSRF = {"X-Reachy-CSRF": "1"}
VOICE = "/owner-recognition/voice/samples"
FACE = "/owner-recognition/face/samples"


def make_client(**kwargs):
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    kwargs.setdefault("enrollment_store", InMemoryEnrollmentStore())
    return TestClient(
        create_app(
            user_store=users,
            registry=InMemoryRobotRegistry(),
            session_store=InMemorySessionStore(),
            audit_log=InMemoryAuditLog(),
            notification_queue=InMemoryNotificationQueue(),
            run_heartbeat_task=False,
            run_telegram_poll_task=False,
            session_secret_key="test-session-secret",
            remote_ui_token="test-token",
            **kwargs,
        )
    )


def login(client):
    return client.post(
        "/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF
    )


def reauth(client, password="correct-password"):
    return client.post("/owner-recognition/reauth", json={"password": password}, headers=CSRF)


def test_status_requires_owner_session_not_bearer_token():
    client = make_client()
    assert client.get("/owner-recognition/status").status_code == 401
    # The REMOTE_UI_TOKEN bearer works for other remote-auth routes but not here.
    assert (
        client.get(
            "/owner-recognition/status", headers={"Authorization": "Bearer test-token"}
        ).status_code
        == 401
    )
    login(client)
    response = client.get("/owner-recognition/status")
    assert response.status_code == 200
    assert response.json() == {
        "voice_samples": [],
        "face_samples": [],
        "reauthenticated": False,
        "reauth_expires_in_seconds": None,
    }


def test_upload_requires_csrf_and_fresh_reauth():
    client = make_client()
    login(client)
    body = b"fake-webm-bytes"
    headers = {"Content-Type": "audio/webm"}
    # No CSRF header at all.
    assert client.post(VOICE, content=body, headers=headers).status_code == 403
    # CSRF present but no fresh reauth yet.
    assert client.post(VOICE, content=body, headers={**headers, **CSRF}).status_code == 401

    assert reauth(client).status_code == 200
    response = client.post(VOICE, content=body, headers={**headers, **CSRF})
    assert response.status_code == 200
    sample = response.json()
    assert sample["kind"] == "voice"
    assert sample["content_type"] == "audio/webm"
    assert sample["size_bytes"] == len(body)

    status = client.get("/owner-recognition/status").json()
    assert len(status["voice_samples"]) == 1
    assert status["reauthenticated"] is True
    assert status["reauth_expires_in_seconds"] > 0


def test_reauth_rejects_wrong_password():
    client = make_client()
    login(client)
    assert reauth(client, password="wrong").status_code == 401
    assert client.post(VOICE, content=b"x", headers={"Content-Type": "audio/webm", **CSRF}).status_code == 401


def test_rejects_unsupported_content_type():
    client = make_client()
    login(client)
    reauth(client)
    response = client.post(VOICE, content=b"not audio", headers={"Content-Type": "text/plain", **CSRF})
    assert response.status_code == 422


def test_face_and_voice_samples_are_kept_separate():
    client = make_client()
    login(client)
    reauth(client)
    client.post(VOICE, content=b"voice-bytes", headers={"Content-Type": "audio/wav", **CSRF})
    client.post(FACE, content=b"face-bytes", headers={"Content-Type": "image/jpeg", **CSRF})
    status = client.get("/owner-recognition/status").json()
    assert len(status["voice_samples"]) == 1
    assert len(status["face_samples"]) == 1
    assert status["voice_samples"][0]["content_type"] == "audio/wav"
    assert status["face_samples"][0]["content_type"] == "image/jpeg"


def test_delete_one_sample():
    client = make_client()
    login(client)
    reauth(client)
    sample = client.post(VOICE, content=b"voice-bytes", headers={"Content-Type": "audio/wav", **CSRF}).json()
    assert client.delete(f"{VOICE}/{sample['sample_id']}", headers=CSRF).status_code == 200
    assert client.delete(f"{VOICE}/{sample['sample_id']}", headers=CSRF).status_code == 404
    assert client.get("/owner-recognition/status").json()["voice_samples"] == []


def test_delete_all_samples():
    client = make_client()
    login(client)
    reauth(client)
    for _ in range(3):
        client.post(VOICE, content=b"voice-bytes", headers={"Content-Type": "audio/wav", **CSRF})
    response = client.delete(VOICE, headers=CSRF)
    assert response.status_code == 200
    assert response.json() == {"deleted": 3}
    assert client.get("/owner-recognition/status").json()["voice_samples"] == []


def test_oversized_sample_rejected_by_content_length():
    client = make_client()
    login(client)
    reauth(client)
    huge = b"a" * (11 * 1024 * 1024)
    response = client.post(VOICE, content=huge, headers={"Content-Type": "audio/wav", **CSRF})
    assert response.status_code == 413


def test_logout_clears_reauth_and_session():
    client = make_client()
    login(client)
    reauth(client)
    assert client.get("/owner-recognition/status").json()["reauthenticated"] is True
    client.post("/auth/logout", headers=CSRF)
    assert client.get("/owner-recognition/status").status_code == 401
