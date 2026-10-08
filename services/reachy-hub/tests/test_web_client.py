"""Phase 47A: the React client's contract with the hub, and its static mount.

`clients/web/src/api/` holds a snapshot of the hub's OpenAPI document and sample
responses taken from a real hub app. The operator routes return bare dicts, so
the OpenAPI schema says nothing about their fields; the samples are what the
TypeScript types are written and tested against. These tests fail when a
response changes shape without the snapshot (and so the client types) being
regenerated:

    python services/reachy-hub/tests/test_web_client.py

Phase 47B adds the planner routes the React client uses (tasks, reminders, notes, receipts). The
`test_planner_*` tests characterize their behaviour through the real owner-session chain
(hub -> core, in-memory stores), so the React replacement is held to what the hub actually does.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
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

from shared.models.receipt import ActionReceipt

CSRF = {"X-Reachy-CSRF": "1"}
ROOT = Path(__file__).resolve().parents[3]
API_DIR = ROOT / "clients" / "web" / "src" / "api"
# Operations the 47A client calls. Anything else is not part of this contract.
OPERATIONS = [
    ("get", "/auth/me"), ("post", "/auth/login"), ("post", "/auth/logout"), ("get", "/status"),
    ("get", "/planner/tasks"), ("post", "/planner/tasks"), ("put", "/planner/tasks/{item_id}"),
    ("delete", "/planner/tasks/{item_id}"), ("post", "/planner/tasks/{item_id}/complete"),
    ("post", "/planner/tasks/{item_id}/reopen"),
    ("get", "/planner/reminders"), ("post", "/planner/reminders"), ("post", "/planner/reminders/{item_id}/complete"),
    ("delete", "/planner/reminders/{item_id}"),
    ("get", "/planner/notes"), ("post", "/planner/notes"), ("put", "/planner/notes/{item_id}"),
    ("delete", "/planner/notes/{item_id}"),
    ("get", "/planner/receipts"),
    ("get", "/planner/alarms"), ("post", "/planner/alarms"), ("patch", "/planner/alarms/{item_id}"),
    ("delete", "/planner/alarms/{item_id}"), ("post", "/planner/alarms/stop"),
    ("get", "/planner/stations"), ("post", "/planner/stations"), ("delete", "/planner/stations/{item_id}"),
    ("get", "/planner/stations/search"),
    ("get", "/chats"), ("post", "/chats"), ("get", "/chats/{chat_id}"), ("delete", "/chats/{chat_id}"),
    ("post", "/messages"), ("get", "/sessions/{user_id}"),
]


def make_client(**hub_options) -> TestClient:
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
    client = TestClient(create_app(
        user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
        run_heartbeat_task=False, run_telegram_poll_task=False,
        session_secret_key="test-session-secret", remote_ui_token="test-token", **hub_options,
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)),
        client_factory=lambda url: EmbodimentClient(url, transport=httpx.ASGITransport(app=embodiment)),
    ))
    client.core = core  # tests seed records the hub cannot create (action receipts) straight into core's store
    return client


def logged_in_client(**hub_options) -> TestClient:
    client = make_client(**hub_options)
    response = client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF)
    assert response.status_code == 200
    client.post("/robots", json={"robot_id": "desk", "base_url": "http://robot"})
    # Give the LLM usage list one entry's worth of shape: an empty list proves nothing about its items.
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}}, headers=CSRF)
    seed_planner(client)
    return client


def seed_planner(client: TestClient) -> None:
    """One of each record kind and state, so every sample list has a representative first item."""
    done = client.post("/planner/tasks", json={"text": "Write report"}, headers=CSRF).json()
    client.post(f"/planner/tasks/{done['id']}/complete", headers=CSRF)
    client.post("/planner/tasks", json={"text": "Water plants"}, headers=CSRF)
    reminder = client.post("/planner/reminders", json={"text": "Call Lisa", "due_at": "2030-01-02T09:00:00Z"}, headers=CSRF).json()
    client.post("/planner/reminders", json={"text": "Book club", "due_at": "2030-02-02T09:00:00Z"}, headers=CSRF)
    client.post(f"/planner/reminders/{reminder['id']}/complete", headers=CSRF)
    client.post("/planner/notes", json={"title": "Groceries", "body": "milk\neggs"}, headers=CSRF)
    station = client.post("/planner/stations", json={"name": "SWR3", "guide_id": "s24896"}, headers=CSRF).json()
    client.post("/planner/alarms", json={"label": "Wake", "time": "07:30", "repeat": [0, 1, 2, 3, 4], "station_id": station["id"], "volume": 120}, headers=CSRF)
    client.post("/planner/alarms", json={"label": "Chime", "time": "21:00"}, headers=CSRF)
    chat = client.post("/chats", json={"user_id": "default-user", "title": "Hello there"}, headers=CSRF).json()
    client.post("/messages", json={"user_id": "default-user", "channel": "web", "text": "what time is it", "input_modality": "text", "chat_id": chat["id"]}, headers=CSRF)
    asyncio.run(client.core.state.planner_store.add_receipt(ActionReceipt(
        action_type="task.created", source_channel="web", object_type="task", fields={"Task": "Water plants"},
    )))
    asyncio.run(client.core.state.planner_store.add_receipt(ActionReceipt(
        action_type="alarm.delivered", status="failed", source_channel="system", object_type="alarm",
        failure_reason="no audio",
    )))


def _union(left, right):
    """Combine two shapes: `null` in one record and a string in another becomes `NoneType|str`."""
    if left == right:
        return left
    if isinstance(left, dict) and isinstance(right, dict):
        return {key: _union(left.get(key), right.get(key)) if key in left and key in right else (left.get(key) or right.get(key))
                for key in sorted(left.keys() | right.keys())}
    if isinstance(left, str) and isinstance(right, str):
        return "|".join(sorted(set(left.split("|")) | set(right.split("|"))))
    return f"{left}|{right}"


def shape(value):
    """Keys and JSON types, not values. A list is the union of its items' shapes (or `[]` when empty)."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        merged = None
        for item in value:
            merged = shape(item) if merged is None else _union(merged, shape(item))
        return [merged] if value else []
    return type(value).__name__


def snapshot(client: TestClient) -> dict:
    chat_id = client.get("/chats", params={"user_id": "default-user"}).json()[0]["id"]
    return {
        "auth_me": client.get("/auth/me").json(),
        "status": client.get("/status").json(),
        "tasks": client.get("/planner/tasks").json(),
        "reminders": client.get("/planner/reminders").json(),
        "notes": client.get("/planner/notes").json(),
        "receipts": client.get("/planner/receipts").json(),
        "alarms": client.get("/planner/alarms").json(),
        "stations": client.get("/planner/stations").json(),
        "chats": client.get("/chats", params={"user_id": "default-user"}).json(),
        "chat": client.get(f"/chats/{chat_id}", params={"user_id": "default-user"}).json(),
        "message": client.post("/messages", json={"user_id": "default-user", "channel": "web", "text": "what time is it", "input_modality": "text", "chat_id": chat_id}, headers=CSRF).json(),
        "session": client.get("/sessions/default-user").json(),
    }


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
    for name in ("tasks", "reminders", "notes", "receipts", "alarms", "stations", "chats", "chat", "message", "session"):
        assert live[name] and saved[name], name  # an empty list would pin no item shape
        assert shape(live[name]) == shape(saved[name]), name


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


PLANNER_READS = [
    "/planner/tasks", "/planner/reminders", "/planner/notes", "/planner/receipts", "/planner/alarms", "/planner/stations",
]


def test_planner_routes_need_the_owner_session_and_mutations_need_csrf():
    anonymous = make_client()
    for path in PLANNER_READS:
        assert anonymous.get(path).status_code == 401, path
    assert anonymous.post("/planner/tasks", json={"text": "x"}, headers=CSRF).status_code == 401
    signed_in = logged_in_client()
    for method, path, body in [
        ("post", "/planner/tasks", {"text": "x"}), ("post", "/planner/notes", {"title": "x"}),
        ("post", "/planner/reminders", {"text": "x", "due_at": "2030-01-01T00:00:00Z"}),
    ]:
        assert getattr(signed_in, method)(path, json=body).status_code == 403, path
    assert signed_in.delete("/planner/tasks/anything").status_code == 403


def test_planner_tasks_behaviour():
    client = logged_in_client()
    created = client.post("/planner/tasks", json={"text": "<b>Sweep</b> garage"}, headers=CSRF).json()
    assert created["status"] == "open" and created["text"] == "<b>Sweep</b> garage"  # stored literally
    listed = client.get("/planner/tasks").json()
    assert {t["status"] for t in listed} == {"open", "done"}  # the unfiltered list carries both states
    assert all(t["status"] == "open" for t in client.get("/planner/tasks?status=open").json())
    assert client.get("/planner/tasks?status=bogus").status_code == 422
    done = client.post(f"/planner/tasks/{created['id']}/complete", headers=CSRF).json()
    assert done["status"] == "done" and done["completed_at"]
    assert client.post(f"/planner/tasks/{created['id']}/reopen", headers=CSRF).json()["status"] == "open"
    assert client.put(f"/planner/tasks/{created['id']}", json={"text": "Renamed"}, headers=CSRF).json()["text"] == "Renamed"
    assert client.delete(f"/planner/tasks/{created['id']}", headers=CSRF).json() == {"deleted": True}
    for call in (
        client.put("/planner/tasks/nope", json={"text": "a"}, headers=CSRF),
        client.post("/planner/tasks/nope/complete", headers=CSRF),
        client.delete("/planner/tasks/nope", headers=CSRF),
    ):
        assert call.status_code == 404 and isinstance(call.json()["detail"], str)
    assert client.post("/planner/tasks", json={"text": ""}, headers=CSRF).status_code == 422
    assert client.post("/planner/tasks", json={"text": "x" * 2001}, headers=CSRF).status_code == 422
    # Classification is fixed at creation: an edit that carries it is refused, not ignored.
    other = client.post("/planner/tasks", json={"text": "keep"}, headers=CSRF).json()
    refused = client.put(f"/planner/tasks/{other['id']}", json={"text": "keep", "sensitivity": "public"}, headers=CSRF)
    assert refused.status_code == 422


def test_planner_reminders_behaviour():
    client = logged_in_client()
    created = client.post("/planner/reminders", json={"text": "Call <i>Lisa</i>", "due_at": "2030-03-04T17:30:00+08:00"}, headers=CSRF).json()
    assert created["status"] == "pending" and created["text"] == "Call <i>Lisa</i>"
    # The instant is preserved whatever offset comes back, so the client parses it as a date, never as a string.
    assert datetime.fromisoformat(created["due_at"]) == datetime(2030, 3, 4, 9, 30, tzinfo=UTC)
    assert client.post(f"/planner/reminders/{created['id']}/complete", headers=CSRF).json()["status"] == "done"
    # The hub has no way to reopen or edit a reminder; the client must not offer either.
    assert client.post(f"/planner/reminders/{created['id']}/reopen", headers=CSRF).status_code in (404, 405)
    assert client.put(f"/planner/reminders/{created['id']}", json={"text": "x"}, headers=CSRF).status_code in (404, 405)
    assert client.delete(f"/planner/reminders/{created['id']}", headers=CSRF).json() == {"deleted": True}
    assert client.post("/planner/reminders/nope/complete", headers=CSRF).status_code == 404
    assert client.post("/planner/reminders", json={"text": "x", "due_at": "not a date"}, headers=CSRF).status_code == 422
    assert client.post("/planner/reminders", json={"text": "x"}, headers=CSRF).status_code == 422


def test_planner_notes_behaviour():
    client = logged_in_client()
    created = client.post("/planner/notes", json={"title": "Trip <b>plan</b>", "body": "book flights"}, headers=CSRF).json()
    assert created["title"] == "Trip <b>plan</b>" and created["updated_at"]
    saved = client.put(f"/planner/notes/{created['id']}", json={"title": "Trip", "body": "book flights and hotel"}, headers=CSRF).json()
    assert saved["body"].endswith("hotel") and saved["updated_at"] >= created["updated_at"]
    assert [n["id"] for n in client.get("/planner/notes", params={"q": "hotel"}).json()] == [created["id"]]
    assert client.get("/planner/notes", params={"q": "zzz-no-match"}).json() == []
    assert client.get("/planner/notes", params={"q": "x" * 201}).status_code == 422
    assert client.post("/planner/notes", json={"title": ""}, headers=CSRF).status_code == 422
    assert client.post("/planner/notes", json={"title": "t", "body": "x" * 20001}, headers=CSRF).status_code == 422
    assert client.put(f"/planner/notes/{created['id']}", json={"title": "t", "sensitivity": "public"}, headers=CSRF).status_code == 422
    assert client.put("/planner/notes/nope", json={"title": "t"}, headers=CSRF).status_code == 404
    assert client.delete(f"/planner/notes/{created['id']}", headers=CSRF).json() == {"deleted": True}
    assert client.delete(f"/planner/notes/{created['id']}", headers=CSRF).status_code == 404


def test_planner_receipts_are_read_only_and_newest_first():
    client = logged_in_client()
    receipts = client.get("/planner/receipts").json()
    kinds = [r["action_type"] for r in receipts]
    # Creating an alarm records its own receipt, so the seeded alarms appear too; the seeded two keep their order.
    assert kinds == ["alarm.delivered", "task.created", "alarm.created", "alarm.created"]  # newest first
    assert receipts[0]["status"] == "failed" and receipts[0]["failure_reason"] == "no audio"
    assert receipts[1]["fields"] == {"Task": "Water plants"}
    assert client.post("/planner/receipts", json={}, headers=CSRF).status_code in (404, 405)


def test_planner_alarms_and_stations_behaviour():
    client = logged_in_client()
    station = client.get("/planner/stations").json()[0]
    created = client.post(
        "/planner/alarms",
        json={"label": "<b>Gym</b>", "time": "06:15", "repeat": [0, 2, 4], "station_id": station["id"], "volume": 150},
        headers=CSRF,
    ).json()
    assert created["label"] == "<b>Gym</b>" and created["status"] == "scheduled" and created["enabled"] is True
    assert created["repeat"] == [0, 2, 4] and created["volume"] == 150 and created["station_id"] == station["id"]
    assert datetime.fromisoformat(created["due_at"]).tzinfo is not None  # an instant: the client shows it in the device's zone
    off = client.patch(f"/planner/alarms/{created['id']}", json={"enabled": False}, headers=CSRF).json()
    assert off["enabled"] is False and off["label"] == "<b>Gym</b>"  # only what was sent changes
    chime = client.patch(f"/planner/alarms/{created['id']}", json={"station_id": None}, headers=CSRF).json()
    assert chime["station_id"] is None  # an explicit null means "chime"
    retimed = client.patch(f"/planner/alarms/{created['id']}", json={"time": "07:45", "repeat": []}, headers=CSRF).json()
    assert retimed["repeat"] == [] and retimed["due_at"] != created["due_at"]
    assert client.post("/planner/alarms/stop", headers=CSRF).json() == {"stopped": False}  # nothing is playing in a test hub
    gone = client.delete(f"/planner/alarms/{created['id']}", headers=CSRF).json()
    assert gone["status"] == "cancelled"
    assert any(a["id"] == created["id"] and a["status"] == "cancelled" for a in client.get("/planner/alarms").json())  # the list still carries it
    for body in ({"label": "x", "time": "25:00"}, {"label": ""}, {"label": "x", "time": "07:00", "volume": 5},
                 {"label": "x", "time": "07:00", "volume": 401}, {"label": "x", "time": "07:00", "repeat": list(range(8))}):
        assert client.post("/planner/alarms", json=body, headers=CSRF).status_code == 422, body
    assert client.patch("/planner/alarms/nope", json={"enabled": True}, headers=CSRF).status_code == 404
    assert client.delete("/planner/alarms/nope", headers=CSRF).status_code == 404

    added = client.post("/planner/stations", json={"name": "Radio <i>X</i>", "guide_id": "s111"}, headers=CSRF).json()
    assert added["name"] == "Radio <i>X</i>"
    assert client.post("/planner/stations", json={"name": "bad", "guide_id": "x1"}, headers=CSRF).status_code == 422
    assert client.delete(f"/planner/stations/{added['id']}", headers=CSRF).json() == {"deleted": True}
    assert client.get("/planner/stations/search", params={"q": "a"}).status_code == 422  # two characters minimum
    assert client.post("/planner/alarms/stop").status_code == 403  # stopping needs the CSRF header like any mutation


def test_chat_behaviour():
    anonymous = make_client()
    assert anonymous.get("/chats", params={"user_id": "u"}).status_code == 401
    client = logged_in_client()
    assert client.post("/chats", json={"user_id": "u", "title": "t"}).status_code == 403
    created = client.post("/chats", json={"user_id": "mine", "title": "<b>Plan</b>"}, headers=CSRF).json()
    assert created["title"] == "<b>Plan</b>" and created["user_id"] == "mine"
    assert client.post("/chats", json={"user_id": "mine", "title": ""}, headers=CSRF).status_code == 422
    assert client.post("/chats", json={"user_id": "mine", "title": "x" * 121}, headers=CSRF).status_code == 422
    # Records are per user id: another id sees none of them and cannot open or delete them.
    assert client.get("/chats", params={"user_id": "other"}).json() == []
    assert client.get(f"/chats/{created['id']}", params={"user_id": "other"}).status_code == 404
    assert client.delete(f"/chats/{created['id']}", params={"user_id": "other"}, headers=CSRF).status_code == 404
    assert client.get("/chats/none", params={"user_id": "mine"}).json() == {"detail": "Chat not found"}

    reply = client.post(
        "/messages", json={"user_id": "mine", "channel": "web", "text": "what time is it", "input_modality": "text", "chat_id": created["id"]},
        headers=CSRF,
    ).json()
    assert reply["reply"] and reply["active_channel"] == "web" and reply["web_search"] is None and reply["context_meeting"] is None
    detail = client.get(f"/chats/{created['id']}", params={"user_id": "mine"}).json()
    assert [t["status"] for t in detail["turns"]] == ["complete"] and detail["turns"][0]["text"] == "what time is it"
    assert detail["turns"][0]["reply"] == reply["reply"]
    session = client.get("/sessions/mine").json()
    assert session["active_channel"] == "web" and session["dnd"] is False and session["interaction_mode"]
    assert client.get("/sessions/nobody").status_code == 404
    assert client.post("/messages", json={"user_id": "mine", "channel": "web", "text": "x", "chat_id": created["id"]}).status_code == 403

    assert client.delete(f"/chats/{created['id']}", params={"user_id": "mine"}, headers=CSRF).status_code == 200
    assert client.get("/chats", params={"user_id": "mine"}).json() == []
    # Deleting the saved record does not forget the assistant's own session.
    assert client.get("/sessions/mine").status_code == 200


def test_owner_bound_chat_is_limited_to_the_owner_account():
    """With an accounts service token (the deployed shape) the hub is owner-bound: `/status` says so, and
    the private work routes need the owner session and the owner's own user id (OWNER_USER_ID, here the default)."""
    anonymous = make_client(accounts_service_token="svc")
    assert anonymous.get("/sessions/default-user").status_code == 401
    assert anonymous.post("/messages", json={"user_id": "default-user", "channel": "web", "text": "x"}, headers=CSRF).status_code == 401
    client = logged_in_client(accounts_service_token="svc")
    assert client.get("/status").json()["owner_bound"] is True
    assert client.get("/sessions/default-user").status_code == 200
    assert client.get("/sessions/someone-else").status_code == 403
    refused = client.post("/messages", json={"user_id": "someone-else", "channel": "web", "text": "x"}, headers=CSRF)
    assert refused.status_code == 403 and refused.json()["detail"] == "This account belongs to the signed-in owner"
    allowed = client.post("/messages", json={"user_id": "default-user", "channel": "web", "text": "what time is it"}, headers=CSRF)
    assert allowed.status_code == 200 and allowed.headers["cache-control"] == "no-store"


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
