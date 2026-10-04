"""Phase 29: reachy-hub's coding_agent_notify_loop actually pushes a
Telegram message once a coding-agent session completes. Chained through
real in-process companion-core and coding-agent-service apps via
httpx.ASGITransport, same pattern as test_telegram.py — a real async task
on a short interval, not a unit test of loop internals (the loop itself is
a private closure inside create_app, same as heartbeat_loop).
"""

import asyncio
import json
import time

import httpx
from coding_agent_service.app import create_app as create_coding_agent_app
from coding_agent_service.providers import SimulatedProvider
from coding_agent_service.store import InMemoryCodingAgentStore
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
from reachy_hub.coding_agent_client import CodingAgentServiceClient
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.telegram_chat_registry import InMemoryTelegramChatRegistry
from reachy_hub.telegram_client import TelegramClient

CODING_AGENT_TOKEN = "fixture-coding-agent-token"


class FakeTelegramBotAPI:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sendMessage"):
            payload = json.loads(request.content)
            self.sent_messages.append((payload["chat_id"], payload["text"]))
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(200, json={"ok": True, "result": []})


def _coding_agent_app():
    return create_coding_agent_app(
        store=InMemoryCodingAgentStore(),
        providers={"simulated": SimulatedProvider()},
        service_token=CODING_AGENT_TOKEN,
    )


def _core_app(coding_agent_app):
    return create_core_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
        coding_agent_base_url="http://coding-agent-service",
        coding_agent_transport=httpx.ASGITransport(app=coding_agent_app),
        coding_agent_service_token=CODING_AGENT_TOKEN,
    )


def test_a_completed_session_is_pushed_to_telegram_within_one_poll_interval() -> None:
    coding_agent_app = _coding_agent_app()
    coding_agent_client_for_setup = TestClient(coding_agent_app)
    headers = {"X-Reachy-Coding-Agent-Service-Token": CODING_AGENT_TOKEN}
    project = coding_agent_client_for_setup.post(
        "/projects", headers=headers,
        json={"name": "Reachy Work Buddy", "repository_path": "/x", "provider": "simulated"},
    ).json()
    coding_agent_client_for_setup.post(
        "/sessions", headers=headers,
        json={"project_id": project["id"], "task_summary": "Refactor module X", "owner_user_id": "owner-1"},
    )

    core_app = _core_app(coding_agent_app)
    fake_api = FakeTelegramBotAPI()
    telegram_client = TelegramClient("fake-token", transport=httpx.MockTransport(fake_api.handler))
    chat_registry = InMemoryTelegramChatRegistry()

    hub_app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
        companion_core_client=CompanionCoreClient(
            "http://companion-core", transport=httpx.ASGITransport(app=core_app)
        ),
        coding_agent_client=CodingAgentServiceClient(
            "http://coding-agent-service", transport=httpx.ASGITransport(app=coding_agent_app),
            service_token=CODING_AGENT_TOKEN,
        ),
        run_heartbeat_task=False,
        run_telegram_poll_task=False,
        telegram_client=telegram_client,
        telegram_chat_registry=chat_registry,
        telegram_default_user_id="owner-1",
        run_coding_agent_notify_task=True,
        coding_agent_notify_interval=0.05,
    )

    async def register_chat() -> None:
        await chat_registry.set_chat_id("owner-1", 4242)

    asyncio.run(register_chat())

    # core_app is reached only via ASGITransport (no lifespan of its own
    # unless something drives it) — nest its own TestClient so
    # app.state.coding_agent_client (set in companion-core's lifespan)
    # actually exists when the /coding-agents/completions/due route runs.
    with TestClient(core_app), TestClient(hub_app):
        deadline = time.monotonic() + 2.0
        while not fake_api.sent_messages and time.monotonic() < deadline:
            time.sleep(0.05)

    assert len(fake_api.sent_messages) == 1
    chat_id, text = fake_api.sent_messages[0]
    assert chat_id == 4242
    assert "Refactor module X" in text


def test_a_session_waiting_for_the_owner_is_pushed_once_with_a_reply_hint() -> None:
    coding_agent_app = _coding_agent_app()
    coding_agent_client_for_setup = TestClient(coding_agent_app)
    headers = {"X-Reachy-Coding-Agent-Service-Token": CODING_AGENT_TOKEN}
    project = coding_agent_client_for_setup.post(
        "/projects", headers=headers,
        json={"name": "X", "repository_path": "/x", "provider": "simulated"},
    ).json()
    coding_agent_client_for_setup.post(
        "/sessions", headers=headers,
        json={"project_id": project["id"], "task_summary": "ask: pick one", "owner_user_id": "owner-1"},
    )

    core_app = _core_app(coding_agent_app)
    fake_api = FakeTelegramBotAPI()
    telegram_client = TelegramClient("fake-token", transport=httpx.MockTransport(fake_api.handler))
    chat_registry = InMemoryTelegramChatRegistry()

    hub_app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        notification_queue=InMemoryNotificationQueue(),
        companion_core_client=CompanionCoreClient(
            "http://companion-core", transport=httpx.ASGITransport(app=core_app)
        ),
        coding_agent_client=CodingAgentServiceClient(
            "http://coding-agent-service", transport=httpx.ASGITransport(app=coding_agent_app),
            service_token=CODING_AGENT_TOKEN,
        ),
        run_heartbeat_task=False,
        run_telegram_poll_task=False,
        telegram_client=telegram_client,
        telegram_chat_registry=chat_registry,
        telegram_default_user_id="owner-1",
        run_coding_agent_notify_task=True,
        coding_agent_notify_interval=0.05,
    )

    async def register_chat() -> None:
        await chat_registry.set_chat_id("owner-1", 4242)

    asyncio.run(register_chat())

    with TestClient(core_app), TestClient(hub_app):
        time.sleep(0.5)

    assert len(fake_api.sent_messages) == 1
    assert "needs your input" in fake_api.sent_messages[0][1]
    assert "/coding_reply" in fake_api.sent_messages[0][1]
