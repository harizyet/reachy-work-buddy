"""reachy-hub tests, chained against a real (in-process) reachy-embodiment
app via httpx.ASGITransport instead of mocks — this exercises the actual
request/response shapes across the service boundary. reachy_embodiment is a
sibling workspace member, importable here only because uv installs all
workspace members into one shared dev venv (see services/reachy-hub/README.md);
production reachy-hub images do not include reachy-embodiment's code.
"""

import time

import httpx
from companion_core.app import create_app as create_core_app
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore


def make_embodiment_app(**kwargs):
    return create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False, **kwargs)


def make_hub_with_core_app(embodiment_app, core_app, **kwargs) -> TestClient:
    app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        companion_core_client=CompanionCoreClient(
            "http://companion-core", transport=httpx.ASGITransport(app=core_app)
        ),
        run_heartbeat_task=False,
        **kwargs,
    )
    return TestClient(app)


def make_hub_client(embodiment_app, *, registry=None, session_store=None, **kwargs) -> TestClient:
    registry = registry or InMemoryRobotRegistry()
    session_store = session_store or InMemorySessionStore()
    app = create_app(
        registry=registry,
        session_store=session_store,
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=False,
        **kwargs,
    )
    return TestClient(app)


def test_health() -> None:
    client = make_hub_client(make_embodiment_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_and_list_robots() -> None:
    client = make_hub_client(make_embodiment_app())
    resp = client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})
    assert resp.status_code == 200

    resp = client.get("/robots")
    assert resp.json() == [{"robot_id": "desk-1", "base_url": "http://desk-1.local"}]


def test_unknown_robot_is_404() -> None:
    client = make_hub_client(make_embodiment_app())
    resp = client.get("/robots/nope/state")
    assert resp.status_code == 404


def test_robot_state_proxies_to_embodiment() -> None:
    client = make_hub_client(make_embodiment_app())
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.get("/robots/desk-1/state")
    assert resp.status_code == 200
    assert resp.json()["embodiment_state"] == "idle"


def test_robot_behaviours_proxies_the_catalogue() -> None:
    client = make_hub_client(make_embodiment_app())
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.get("/robots/desk-1/behaviours")
    assert resp.status_code == 200
    assert "listening" in resp.json()


def test_trigger_behaviour_proxies_and_updates_embodiment_state() -> None:
    client = make_hub_client(make_embodiment_app())
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.post("/robots/desk-1/behaviour/greeting")
    assert resp.status_code == 200
    assert resp.json()["last_behaviour"] == "greeting"

    resp = client.get("/robots/desk-1/state")
    assert resp.json()["last_behaviour"] == "greeting"


def test_trigger_unknown_behaviour_proxies_404_from_embodiment() -> None:
    client = make_hub_client(make_embodiment_app())
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.post("/robots/desk-1/behaviour/moonwalk")
    assert resp.status_code == 404


def test_heartbeat_background_task_pings_registered_robots() -> None:
    embodiment_app = make_embodiment_app()
    registry = InMemoryRobotRegistry()
    hub_app = create_app(
        registry=registry,
        session_store=InMemorySessionStore(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=True,
        heartbeat_interval=0.05,
    )

    with TestClient(hub_app) as client:  # __enter__ runs lifespan, starting the heartbeat task
        client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})
        time.sleep(0.2)

    assert embodiment_app.state.service_state.last_heartbeat_at is not None


def test_get_session_404_for_unknown_user() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    resp = client.get("/sessions/nobody")
    assert resp.status_code == 404


def test_post_message_creates_a_session_and_forwards_to_companion_core() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())

    resp = client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_channel"] == "reachy"
    assert "hello" in body["reply"]

    session_resp = client.get("/sessions/hariz")
    assert session_resp.status_code == 200
    session = session_resp.json()
    assert session["session_id"] == body["session_id"]
    assert session["conversation_id"] == body["conversation_id"]
    assert session["active_channel"] == "reachy"


def test_two_test_clients_share_one_conversation_state_across_channels() -> None:
    """Phase 5 exit criterion: two test clients share one conversation
    state. client_a and client_b are independent TestClient instances
    (standing in for e.g. Reachy's voice loop and a Telegram bot process)
    hitting the same running reachy-hub — not the same Python object."""
    embodiment_app = make_embodiment_app()
    core_app = create_core_app()
    hub_app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        companion_core_client=CompanionCoreClient(
            "http://companion-core", transport=httpx.ASGITransport(app=core_app)
        ),
        run_heartbeat_task=False,
    )

    client_a = TestClient(hub_app)
    client_b = TestClient(hub_app)

    resp_a = client_a.post(
        "/messages", json={"user_id": "hariz", "channel": "reachy", "text": "what's next on my calendar"}
    )
    assert resp_a.status_code == 200
    body_a = resp_a.json()
    assert "turn 1" in body_a["reply"]

    resp_b = client_b.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "continue there"})
    assert resp_b.status_code == 200
    body_b = resp_b.json()

    # Same session/conversation identity observed by a wholly independent client.
    assert body_b["session_id"] == body_a["session_id"]
    assert body_b["conversation_id"] == body_a["conversation_id"]
    # Channel switched to whoever spoke most recently.
    assert body_b["active_channel"] == "telegram"
    # companion-core's own turn counter advanced across the channel switch —
    # genuinely shared conversation state, not just session metadata.
    assert "turn 2" in body_b["reply"]

    # A third, independent reader agrees with what both clients saw.
    client_c = TestClient(hub_app)
    session = client_c.get("/sessions/hariz").json()
    assert session["session_id"] == body_a["session_id"]
    assert session["active_channel"] == "telegram"


def test_different_users_get_different_sessions() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    resp_1 = client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hi"})
    resp_2 = client.post("/messages", json={"user_id": "someone-else", "channel": "reachy", "text": "hi"})
    assert resp_1.json()["session_id"] != resp_2.json()["session_id"]


def test_new_session_defaults_to_desk_mode_and_routes_to_reachy() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    resp = client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hi"})
    body = resp.json()
    assert body["delivery_channel"] == "reachy"

    session = client.get("/sessions/hariz").json()
    assert session["interaction_mode"] == "desk"


def test_set_mode_404_for_unknown_user() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    resp = client.patch("/sessions/nobody/mode", json={"interaction_mode": "office"})
    assert resp.status_code == 404


def test_mode_change_alone_changes_delivery_channel_without_touching_the_message_text() -> None:
    """Phase 6 exit criterion: mode changes output routing without prompt
    changes. Same exact text sent twice on the same channel; only the
    session's interaction_mode differs between the two calls — the resolved
    delivery_channel must differ deterministically as a result."""
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    text = "what's on my calendar today"

    resp_desk = client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": text})
    assert resp_desk.json()["delivery_channel"] == "reachy"  # Desk is the default mode

    mode_resp = client.patch("/sessions/hariz/mode", json={"interaction_mode": "office"})
    assert mode_resp.status_code == 200
    assert mode_resp.json()["interaction_mode"] == "office"

    resp_office = client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": text})
    assert resp_office.json()["delivery_channel"] == "phone"

    # The text sent was byte-for-byte identical both times; only the reply's
    # turn count (genuine conversation progression) differs, not the input.
    assert "heard: what's on my calendar today" in resp_desk.json()["reply"]
    assert "heard: what's on my calendar today" in resp_office.json()["reply"]


def test_silent_mode_falls_back_to_web_when_active_channel_is_reachy() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hi"})
    client.patch("/sessions/hariz/mode", json={"interaction_mode": "silent"})

    resp = client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hi again"})
    assert resp.json()["delivery_channel"] == "web"
