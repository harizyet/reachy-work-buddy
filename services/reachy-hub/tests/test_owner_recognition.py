"""Phase 25a.2/25b.3 owner-recognition benchmark-capture portal skeleton
(docs/phase-25.md, reachy_hub/owner_recognition.py). Phase 26d benchmark-
vs-operational data policy: raw sample capture only, explicitly enabled,
encrypted at rest when persisted -- no biometric template/model exists
yet."""

import asyncio
import io
import zipfile

from fastapi.testclient import TestClient
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.enrollment_store import InMemoryEnrollmentStore
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

CSRF = {"X-Reachy-CSRF": "1"}
VOICE = "/owner-recognition/benchmark/voice/samples"
FACE = "/owner-recognition/benchmark/face/samples"
ENABLED = "/owner-recognition/benchmark/enabled"


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


def enable_benchmark(client, enabled=True):
    return client.put(ENABLED, json={"enabled": enabled}, headers=CSRF)


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
        "benchmark_enabled": False,
        "voice_samples": [],
        "face_samples": [],
        "voice_total_bytes": 0,
        "face_total_bytes": 0,
        "reauthenticated": False,
        "reauth_expires_in_seconds": None,
    }


def test_upload_requires_csrf_fresh_reauth_and_benchmark_enabled():
    client = make_client()
    login(client)
    body = b"fake-webm-bytes"
    headers = {"Content-Type": "audio/webm"}
    # No CSRF header at all.
    assert client.post(VOICE, content=body, headers=headers).status_code == 403
    # CSRF present but no fresh reauth yet.
    assert client.post(VOICE, content=body, headers={**headers, **CSRF}).status_code == 401

    assert reauth(client).status_code == 200
    # Reauthenticated, but benchmark mode not yet explicitly enabled.
    assert client.post(VOICE, content=body, headers={**headers, **CSRF}).status_code == 403

    assert enable_benchmark(client).status_code == 200
    response = client.post(VOICE, content=body, headers={**headers, **CSRF})
    assert response.status_code == 200
    sample = response.json()
    assert sample["kind"] == "voice"
    assert sample["content_type"] == "audio/webm"
    assert sample["size_bytes"] == len(body)

    status = client.get("/owner-recognition/status").json()
    assert status["benchmark_enabled"] is True
    assert len(status["voice_samples"]) == 1
    assert status["voice_total_bytes"] == len(body)
    assert status["reauthenticated"] is True
    assert status["reauth_expires_in_seconds"] > 0


def test_disabling_benchmark_mode_blocks_new_uploads_but_keeps_existing_samples():
    client = make_client()
    login(client)
    reauth(client)
    enable_benchmark(client)
    client.post(VOICE, content=b"voice-bytes", headers={"Content-Type": "audio/wav", **CSRF})
    enable_benchmark(client, enabled=False)
    response = client.post(VOICE, content=b"more-bytes", headers={"Content-Type": "audio/wav", **CSRF})
    assert response.status_code == 403
    status = client.get("/owner-recognition/status").json()
    assert status["benchmark_enabled"] is False
    assert len(status["voice_samples"]) == 1  # not deleted by disabling


def test_reauth_rejects_wrong_password():
    client = make_client()
    login(client)
    assert reauth(client, password="wrong").status_code == 401
    enable_benchmark(client)
    assert client.post(VOICE, content=b"x", headers={"Content-Type": "audio/webm", **CSRF}).status_code == 401


def test_rejects_unsupported_content_type():
    client = make_client()
    login(client)
    reauth(client)
    enable_benchmark(client)
    response = client.post(VOICE, content=b"not audio", headers={"Content-Type": "text/plain", **CSRF})
    assert response.status_code == 422


def test_face_and_voice_samples_are_kept_separate():
    client = make_client()
    login(client)
    reauth(client)
    enable_benchmark(client)
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
    enable_benchmark(client)
    sample = client.post(VOICE, content=b"voice-bytes", headers={"Content-Type": "audio/wav", **CSRF}).json()
    assert client.delete(f"{VOICE}/{sample['sample_id']}", headers=CSRF).status_code == 200
    assert client.delete(f"{VOICE}/{sample['sample_id']}", headers=CSRF).status_code == 404
    assert client.get("/owner-recognition/status").json()["voice_samples"] == []


def test_delete_all_samples():
    client = make_client()
    login(client)
    reauth(client)
    enable_benchmark(client)
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
    enable_benchmark(client)
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


def test_export_requires_fresh_reauth_but_not_csrf():
    client = make_client()
    login(client)
    reauth(client)
    enable_benchmark(client)
    client.post(VOICE, content=b"voice-bytes", headers={"Content-Type": "audio/wav", **CSRF})
    # GET export needs no CSRF header, only owner session + fresh reauth.
    response = client.get('/owner-recognition/benchmark/voice/export')
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert "manifest.json" in names
    assert any(name.endswith(".wav") for name in names)


def test_export_without_fresh_reauth_is_rejected():
    client = make_client()
    login(client)
    response = client.get('/owner-recognition/benchmark/voice/export')
    assert response.status_code == 401
