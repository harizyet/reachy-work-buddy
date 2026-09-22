"""companion-core tests, chained through real (in-process) reachy-hub and
reachy-embodiment apps via nested httpx.ASGITransport — proves the full
Phase 4 chain (companion-core -> reachy-hub -> reachy-embodiment) without
mocks or real sockets. Both sibling services are importable here only
because uv installs all workspace members into one shared dev venv.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app as create_hub_app
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.robot_registry import InMemoryRobotRegistry, Robot
from reachy_hub.session_store import InMemorySessionStore


def make_chain(*, registered_robots: Sequence[Robot] = ()) -> TestClient:
    embodiment_app = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    registry = InMemoryRobotRegistry()
    registry._robots = {robot.robot_id: robot for robot in registered_robots}
    hub_app = create_hub_app(
        registry=registry,
        session_store=InMemorySessionStore(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=False,
    )
    core_app = create_app(
        hub_base_url="http://reachy-hub",
        transport=httpx.ASGITransport(app=hub_app),
        calendar_store=InMemoryCalendarStore(),
    )
    return TestClient(core_app)


def test_health() -> None:
    with make_chain() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_debug_robot_state_returns_404_for_unregistered_robot() -> None:
    with make_chain() as client:
        resp = client.get("/debug/robots/desk-1/state")
        assert resp.status_code == 404


def test_conversation_turn_replies_and_counts_turns() -> None:
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "hello"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["turn_count"] == 1
        assert "hello" in body["reply"]

        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "telegram", "text": "and now?"},
        )
        assert resp.json()["turn_count"] == 2


def test_conversation_turn_history_is_isolated_per_session() -> None:
    with make_chain() as client:
        client.post(
            "/conversation", json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "hi"}
        )
        resp = client.post(
            "/conversation", json={"session_id": "s2", "conversation_id": "c2", "channel": "reachy", "text": "hi"}
        )
        assert resp.json()["turn_count"] == 1  # a different session starts its own count


def test_whats_next_answers_from_real_calendar_data() -> None:
    """Phase 10 exit criterion: "What's next?" works, using genuinely
    stored calendar data rather than the generic placeholder reply."""
    with make_chain() as client:
        resp = client.get("/calendar/next")
        assert resp.status_code == 200
        assert resp.json() is None  # nothing stored yet

        create_resp = client.post(
            "/calendar/events",
            json={
                "title": "Team Standup",
                "start": "2099-01-05T10:00:00Z",
                "end": "2099-01-05T10:30:00Z",
                "location": "Room 4",
            },
        )
        assert create_resp.status_code == 200

        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what's next"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Team Standup" in body["reply"]
        assert "Room 4" in body["reply"]
        assert body["privacy"] == "work-private"


def test_whats_next_with_no_events_still_answers() -> None:
    with make_chain() as client:
        resp = client.post(
            "/conversation",
            json={"session_id": "s1", "conversation_id": "c1", "channel": "reachy", "text": "what's next"},
        )
        assert resp.json()["reply"] == "You have nothing else on your calendar."


def test_calendar_list_and_free_busy() -> None:
    with make_chain() as client:
        client.post(
            "/calendar/events",
            json={"title": "Lunch", "start": "2099-01-05T12:00:00Z", "end": "2099-01-05T13:00:00Z"},
        )

        list_resp = client.get(
            "/calendar/events", params={"start": "2099-01-05T00:00:00Z", "end": "2099-01-06T00:00:00Z"}
        )
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["title"] == "Lunch"

        fb_resp = client.get(
            "/calendar/free-busy", params={"start": "2099-01-05T00:00:00Z", "end": "2099-01-06T00:00:00Z"}
        )
        assert fb_resp.status_code == 200
        assert "title" not in fb_resp.json()[0]  # free/busy reveals no event details
        assert fb_resp.json()[0]["start"] == "2099-01-05T12:00:00Z"


def test_reminders_due_endpoint() -> None:
    with make_chain() as client:
        soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        later = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
        client.post("/calendar/events", json={"title": "Soon", "start": soon, "end": soon})
        client.post("/calendar/events", json={"title": "Later", "start": later, "end": later})

        resp = client.get("/calendar/reminders/due", params={"within_minutes": 15})
        assert resp.status_code == 200
        reminders = resp.json()
        assert len(reminders) == 1
        assert "Soon" in reminders[0]["text"]
        assert reminders[0]["privacy"] == "work-private"
        assert reminders[0]["urgency"] == "urgent"


def test_debug_trigger_behaviour_reaches_reachy_embodiment_through_the_hub() -> None:
    # The robot is registered directly with reachy-hub, not through
    # companion-core: companion-core has no /robots endpoint of its own
    # (ADR 0001 — robot registry belongs to reachy-hub, not companion-core).
    robot = Robot(robot_id="desk-1", base_url="http://desk-1.local")
    with make_chain(registered_robots=[robot]) as client:
        resp = client.post("/debug/robots/desk-1/behaviour/greeting")
        assert resp.status_code == 200
        assert resp.json()["last_behaviour"] == "greeting"

        state_resp = client.get("/debug/robots/desk-1/state")
        assert state_resp.status_code == 200
        assert state_resp.json()["last_behaviour"] == "greeting"
