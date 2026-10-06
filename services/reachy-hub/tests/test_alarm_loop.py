"""Phase 38.4: the hub's alarm loop against a real in-process companion-core.

No robot is registered, so every alarm takes the privacy/unavailable route and
reaches Telegram; the full policy table is in test_alarm_delivery.py.
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

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
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.telegram_chat_registry import InMemoryTelegramChatRegistry
from reachy_hub.telegram_client import TelegramClient

PAST = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()


def _run(setup) -> tuple[list[str], TestClient]:
    core_app = create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
    )
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sendMessage"):
            sent.append(json.loads(request.content)["text"])
        return httpx.Response(200, json={"ok": True, "result": []})

    chats = InMemoryTelegramChatRegistry()
    asyncio.run(chats.set_chat_id("default-user", 4242))
    hub_app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
        companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core_app)),
        run_heartbeat_task=False,
        run_telegram_poll_task=False,
        telegram_client=TelegramClient("t", transport=httpx.MockTransport(handler)),
        telegram_chat_registry=chats,
        telegram_default_user_id="default-user",
        run_coding_agent_notify_task=True,
        coding_agent_notify_interval=0.05,
        alarm_poll_interval=0.05,
    )
    core = TestClient(core_app)
    with core, TestClient(hub_app):
        setup(core)
        time.sleep(1.0)
    return sent, core


def test_a_due_alarm_reaches_telegram_and_records_the_route() -> None:
    sent, core = _run(lambda c: c.post("/alarms", json={"label": "cake", "due_at": PAST}))
    assert sent == ["Alarm: cake"]
    assert core.get("/alarms").json()[0]["delivery"] == "telegram: privacy mode"


def test_a_reminder_with_an_alarm_notifies_once_through_the_alarm() -> None:
    def setup(c: TestClient) -> None:
        reminder = c.post("/reminders", json={"text": "get cake", "due_at": PAST}).json()
        c.post("/alarms", json={"label": "cake", "due_at": PAST, "reminder_id": reminder["id"]})
        c.post("/reminders", json={"text": "plain", "due_at": PAST})

    sent, _ = _run(setup)
    assert sorted(sent) == ["Alarm: cake", "Reminder: plain"]


def test_a_notify_receipt_reaches_telegram_exactly_once() -> None:
    def setup(c: TestClient) -> None:
        c.post("/conversation", json={"session_id": "s", "conversation_id": "c", "channel": "web", "text": "remind me to feed fish"})
        c.post("/conversation", json={"session_id": "t", "conversation_id": "c", "channel": "telegram", "text": "remind me to skip"})

    sent, core = _run(setup)
    assert sent == ["Task added.\n\nTask: feed fish"]
    assert len(core.get("/receipts").json()) == 2
