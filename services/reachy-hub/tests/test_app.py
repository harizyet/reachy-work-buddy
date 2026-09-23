"""reachy-hub tests, chained against a real (in-process) reachy-embodiment
app via httpx.ASGITransport instead of mocks — this exercises the actual
request/response shapes across the service boundary. reachy_embodiment is a
sibling workspace member, importable here only because uv installs all
workspace members into one shared dev venv (see services/reachy-hub/README.md);
production reachy-hub images do not include reachy-embodiment's code.
"""

import time
from datetime import UTC, datetime, timedelta

import httpx
from companion_core.app import create_app as _create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
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


def create_core_app(**kwargs):
    kwargs.setdefault("calendar_store", InMemoryCalendarStore())
    kwargs.setdefault("task_store", InMemoryTaskStore())
    kwargs.setdefault("memory_store", InMemoryMemoryStore())
    kwargs.setdefault("rag_store", InMemoryDocumentStore())
    kwargs.setdefault("email_store", InMemoryEmailStore())
    kwargs.setdefault("confirmation_store", InMemoryConfirmationStore())
    kwargs.setdefault("llm_settings_store", InMemoryLLMSettingsStore())
    kwargs.setdefault("llm_usage_store", InMemoryLLMUsageStore())
    kwargs.setdefault("persona_store", InMemoryPersonaStore())
    kwargs.setdefault("run_email_dispatch_task", False)
    return _create_core_app(**kwargs)


def make_embodiment_app(**kwargs):
    return create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False, **kwargs)


# Phase 16/ADR 0013: every /robots/{robot_id}/... call in this file needs
# this header now that those routes are auth-gated. A fixed test token
# (not None) is the default here so existing tests keep exercising the
# routes themselves rather than the 401/503 auth paths — those get their
# own dedicated tests below.
TEST_REMOTE_TOKEN = "test-remote-token"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_REMOTE_TOKEN}"}


def make_hub_with_core_app(embodiment_app, core_app, **kwargs) -> TestClient:
    kwargs.setdefault("remote_ui_token", TEST_REMOTE_TOKEN)
    app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        companion_core_client=CompanionCoreClient(
            "http://companion-core", transport=httpx.ASGITransport(app=core_app)
        ),
        run_heartbeat_task=False,
        **kwargs,
    )
    client = TestClient(app)
    client.headers.update(AUTH_HEADERS)
    return client


def make_hub_client(
    embodiment_app, *, registry=None, session_store=None, audit_log=None, notification_queue=None, **kwargs
) -> TestClient:
    registry = registry or InMemoryRobotRegistry()
    session_store = session_store or InMemorySessionStore()
    audit_log = audit_log or InMemoryAuditLog()
    notification_queue = notification_queue or InMemoryNotificationQueue()
    kwargs.setdefault("remote_ui_token", TEST_REMOTE_TOKEN)
    app = create_app(
        registry=registry,
        session_store=session_store,
        audit_log=audit_log,
        notification_queue=notification_queue,
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        run_heartbeat_task=False,
        **kwargs,
    )
    client = TestClient(app)
    client.headers.update(AUTH_HEADERS)
    return client


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
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
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
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        companion_core_client=CompanionCoreClient(
            "http://companion-core", transport=httpx.ASGITransport(app=core_app)
        ),
        run_heartbeat_task=False,
    )

    client_a = TestClient(hub_app)
    client_b = TestClient(hub_app)

    # Ordinary text — this test is about session sharing across channels
    # (Phase 5), not calendar answering. "what's next"-style text is
    # deliberately avoided: Phase 10's calendar-intent matcher would
    # intercept it and reply with a real (if event-less) calendar answer
    # instead of the generic placeholder-reasoning reply this test checks
    # the turn-count format of.
    resp_a = client_a.post(
        "/messages", json={"user_id": "hariz", "channel": "reachy", "text": "what's the weather like"}
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
    delivery_channel must differ deterministically as a result.

    Deliberately uses ordinary/public text — this test is about mode-only
    routing (Phase 6). A calendar-flavored example was used here originally
    and started failing once Phase 9 landed real content-based privacy
    overrides: "calendar" is one of Phase 9's own work-private keywords, so
    Desk mode no longer routed it to Reachy. That's Phase 9 correctly doing
    its job, not a bug — see
    test_private_content_is_never_spoken_via_reachy_even_in_desk_mode below
    for the test that exercises exactly that interaction on purpose.
    """
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    text = "what's the weather like today"

    resp_desk = client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": text})
    assert resp_desk.json()["delivery_channel"] == "reachy"  # Desk is the default mode

    mode_resp = client.patch("/sessions/hariz/mode", json={"interaction_mode": "office"})
    assert mode_resp.status_code == 200
    assert mode_resp.json()["interaction_mode"] == "office"

    resp_office = client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": text})
    assert resp_office.json()["delivery_channel"] == "phone"

    # The text sent was byte-for-byte identical both times; only the reply's
    # turn count (genuine conversation progression) differs, not the input.
    assert "heard: what's the weather like today" in resp_desk.json()["reply"]
    assert "heard: what's the weather like today" in resp_office.json()["reply"]


def test_silent_mode_falls_back_to_web_when_active_channel_is_reachy() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hi"})
    client.patch("/sessions/hariz/mode", json={"interaction_mode": "silent"})

    resp = client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hi again"})
    assert resp.json()["delivery_channel"] == "web"


def test_private_content_is_never_spoken_via_reachy_even_in_desk_mode() -> None:
    """Phase 9: the router has final authority over privacy, overriding
    what mode alone would otherwise pick. Desk mode normally always routes
    to Reachy (Phase 6) — a real difference from that default, not just a
    restatement of Office mode already avoiding Reachy."""
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())

    resp = client.post(
        "/messages", json={"user_id": "hariz", "channel": "telegram", "text": "what is my salary this year"}
    )
    body = resp.json()
    assert body["privacy"] == "sensitive"
    assert body["delivery_channel"] != "reachy"
    assert body["delivery_channel"] == "telegram"  # falls back to the active channel


def test_private_test_payload_cannot_be_spoken_in_office_mode() -> None:
    """Phase 9 exit criterion, literal wording."""
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    client.patch("/sessions/hariz/mode", json={"interaction_mode": "office"})

    resp = client.post(
        "/messages", json={"user_id": "hariz", "channel": "telegram", "text": "this is confidential information"}
    )
    body = resp.json()
    assert body["privacy"] == "sensitive"
    assert body["delivery_channel"] != "reachy"


def test_audit_log_records_the_routing_decision_and_override() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hello there"})
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "what is my salary"})

    entries = client.get("/audit/hariz").json()
    assert len(entries) == 2

    # Most recent first.
    sensitive_entry, public_entry = entries
    assert sensitive_entry["privacy"] == "sensitive"
    assert sensitive_entry["base_channel"] == "reachy"  # Desk mode would have spoken it
    assert sensitive_entry["delivery_channel"] == "telegram"
    assert sensitive_entry["overridden"] is True

    assert public_entry["privacy"] == "public"
    assert public_entry["overridden"] is False
    assert public_entry["base_channel"] == public_entry["delivery_channel"] == "reachy"


def test_audit_log_is_scoped_per_user() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hi"})
    client.post("/messages", json={"user_id": "someone-else", "channel": "reachy", "text": "hi"})

    assert len(client.get("/audit/hariz").json()) == 1
    assert len(client.get("/audit/someone-else").json()) == 1


def test_check_reminders_404_for_unknown_user() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    resp = client.post("/calendar/check-reminders/nobody")
    assert resp.status_code == 404


def test_check_reminders_routes_through_the_same_policy_as_messages() -> None:
    """Phase 10 exit criterion: meeting reminders route appropriately — by
    reusing Phase 6/9's routing exactly, not new logic."""
    core_app = create_core_app()
    client = make_hub_with_core_app(make_embodiment_app(), core_app)

    # Establish a session (Desk mode by default) via an ordinary message.
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})

    # calendar_store is injected synchronously (outside lifespan) by the
    # create_core_app wrapper above, so a bare (non-`with`) TestClient can
    # reach it directly — same reason the hub's ASGITransport call into
    # core_app for /conversation works without running core_app's lifespan.
    core_client = TestClient(core_app)
    soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    core_client.post("/calendar/events", json={"title": "Standup", "start": soon, "end": soon})

    resp = client.post("/calendar/check-reminders/hariz", params={"within_minutes": 15})
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert "Standup" in results[0]["text"]
    # Desk mode's base channel is Reachy, but the reminder is classified
    # work-private (calendar content) — same override as any other message.
    assert results[0]["delivery_channel"] != "reachy"

    audit = client.get("/audit/hariz").json()
    reminder_entry = audit[0]  # most recent
    assert reminder_entry["privacy"] == "work-private"
    assert reminder_entry["overridden"] is True


def test_check_reminders_returns_empty_list_when_nothing_is_due() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})

    resp = client.post("/calendar/check-reminders/hariz")
    assert resp.status_code == 200
    assert resp.json() == []


# --- Phase 17: interruption intelligence (docs/adr/0014) ---


def _seed_reminder(core_app, *, minutes_out: float, title: str = "Standup") -> None:
    core_client = TestClient(core_app)
    start = (datetime.now(UTC) + timedelta(minutes=minutes_out)).isoformat()
    core_client.post("/calendar/events", json={"title": title, "start": start, "end": start})


def test_routine_reminder_defers_to_queue_while_dnd_is_on() -> None:
    """Phase 17 exit criterion: routine notifications defer correctly while
    the user is occupied."""
    core_app = create_core_app()
    client = make_hub_with_core_app(make_embodiment_app(), core_app)
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})
    client.patch("/sessions/hariz/dnd", json={"dnd": True})

    # 10 minutes out grades NORMAL (companion-core's reminders_due only
    # grades URGENT within 5 minutes) -> occupied + NORMAL -> QUEUE.
    _seed_reminder(core_app, minutes_out=10)

    resp = client.post("/calendar/check-reminders/hariz")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["action"] == "queue"
    assert results[0]["delivered"] is False

    queued = client.get("/notifications/hariz").json()
    assert len(queued) == 1
    assert "Standup" in queued[0]["text"]


def test_urgent_reminder_still_gestures_while_occupied() -> None:
    core_app = create_core_app()
    embodiment_app = make_embodiment_app()
    client = make_hub_with_core_app(embodiment_app, core_app)
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})
    client.patch("/sessions/hariz/dnd", json={"dnd": True})

    # 2 minutes out grades URGENT -> occupied + URGENT -> GESTURE.
    _seed_reminder(core_app, minutes_out=2)

    resp = client.post("/calendar/check-reminders/hariz")
    assert resp.status_code == 200
    results = resp.json()
    assert results[0]["action"] == "gesture"

    # A real robot was registered and reachable (real in-process embodiment
    # app, per this file's ASGITransport convention), so the gesture actually
    # fired rather than downgrading to TEXT.
    state = client.get("/robots/desk-1/state").json()
    assert state["last_behaviour"] == "important_notice"


def test_queued_notifications_flush_when_dnd_turns_off() -> None:
    core_app = create_core_app()
    client = make_hub_with_core_app(make_embodiment_app(), core_app)
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})
    client.patch("/sessions/hariz/dnd", json={"dnd": True})
    _seed_reminder(core_app, minutes_out=10)
    client.post("/calendar/check-reminders/hariz")
    assert len(client.get("/notifications/hariz").json()) == 1

    resp = client.patch("/sessions/hariz/dnd", json={"dnd": False})
    assert resp.status_code == 200
    assert client.get("/notifications/hariz").json() == []

    audit = client.get("/audit/hariz").json()
    assert audit[0]["action"] == "interrupt"


def test_leaving_meeting_privacy_context_flushes_queue() -> None:
    core_app = create_core_app()
    client = make_hub_with_core_app(make_embodiment_app(), core_app)
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})
    client.patch("/sessions/hariz/privacy-context", json={"privacy_context": "meeting"})
    _seed_reminder(core_app, minutes_out=10)
    client.post("/calendar/check-reminders/hariz")
    assert len(client.get("/notifications/hariz").json()) == 1

    client.patch("/sessions/hariz/privacy-context", json={"privacy_context": "unknown"})
    assert client.get("/notifications/hariz").json() == []


# --- Phase 18: daily briefing (docs/adr/0015) ---


def test_briefing_404_for_unknown_user() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    resp = client.post("/briefing/nobody")
    assert resp.status_code == 404


def test_briefing_greets_and_delivers_privately() -> None:
    """Phase 18 exit criterion: "Reachy greets; detailed briefing is
    privately delivered."""
    core_app = create_core_app()
    embodiment_app = make_embodiment_app()
    client = make_hub_with_core_app(embodiment_app, core_app)
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    core_client = TestClient(core_app)
    soon = (datetime.now(UTC) + timedelta(minutes=3)).isoformat()
    core_client.post("/calendar/events", json={"title": "Standup", "start": soon, "end": soon})

    resp = client.post("/briefing/hariz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["greeted"] is True
    assert any("Standup" in item["text"] for item in body["items"])
    assert "Standup" in body["text"]
    # Desk mode's base channel is Reachy, but a briefing is forced
    # work-private, so it can never land on Reachy's speaker.
    assert body["delivery_channel"] != "reachy"

    # The greeting gesture actually fired on the real (simulated) robot.
    state = client.get("/robots/desk-1/state").json()
    assert state["last_behaviour"] == "greeting"


def test_briefing_defers_detailed_content_while_dnd_is_on() -> None:
    """The greeting still happens (arrival is unconditional), but the
    detailed content is queued, same as a routine reminder would be."""
    core_app = create_core_app()
    embodiment_app = make_embodiment_app()
    client = make_hub_with_core_app(embodiment_app, core_app)
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})
    client.patch("/sessions/hariz/dnd", json={"dnd": True})

    core_client = TestClient(core_app)
    later = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    core_client.post("/calendar/events", json={"title": "Later standup", "start": later, "end": later})

    resp = client.post("/briefing/hariz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["greeted"] is True
    assert body["action"] == "queue"
    assert body["delivered"] is False

    queued = client.get("/notifications/hariz").json()
    assert len(queued) == 1
    assert "Later standup" in queued[0]["text"]


def test_briefing_with_nothing_to_report_still_greets() -> None:
    client = make_hub_with_core_app(make_embodiment_app(), create_core_app())
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})
    client.post("/robots", json={"robot_id": "desk-1", "base_url": "http://desk-1.local"})

    resp = client.post("/briefing/hariz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["greeted"] is True
    assert body["items"] == []
    assert body["text"] == "Nothing on your briefing right now."


def test_manual_flush_endpoint_delivers_queued_notifications() -> None:
    core_app = create_core_app()
    client = make_hub_with_core_app(make_embodiment_app(), core_app)
    client.post("/messages", json={"user_id": "hariz", "channel": "telegram", "text": "hi"})
    client.patch("/sessions/hariz/dnd", json={"dnd": True})
    _seed_reminder(core_app, minutes_out=10)
    client.post("/calendar/check-reminders/hariz")

    resp = client.post("/notifications/hariz/flush")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["action"] == "interrupt"
    assert client.get("/notifications/hariz").json() == []
