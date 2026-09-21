"""Telegram integration tests, driven against httpx.MockTransport (a fake
Bot API) rather than the real network — see AGENTS.md testing conventions.
No real token or network access needed for these; the real live proof for
Phase 7 is a manual run against the real Telegram Bot API (see
services/reachy-hub/README.md).
"""

import json
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
from reachy_hub.telegram_chat_registry import InMemoryTelegramChatRegistry
from reachy_hub.telegram_client import TelegramClient


class FakeTelegramBotAPI:
    """In-memory stand-in for api.telegram.org: queues of updates to
    return from getUpdates, and records sendMessage calls."""

    def __init__(self) -> None:
        self.pending_updates: list[dict] = []
        self.sent_messages: list[tuple[int, str]] = []
        self._next_update_id = 1

    def enqueue_text_message(self, chat_id: int, text: str) -> None:
        self.pending_updates.append(
            {
                "update_id": self._next_update_id,
                "message": {"chat": {"id": chat_id}, "text": text},
            }
        )
        self._next_update_id += 1

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getUpdates"):
            updates, self.pending_updates = self.pending_updates, []
            return httpx.Response(200, json={"ok": True, "result": updates})
        if request.url.path.endswith("/sendMessage"):
            body = json.loads(request.content)
            self.sent_messages.append((body["chat_id"], body["text"]))
            return httpx.Response(200, json={"ok": True, "result": {}})
        raise AssertionError(f"unexpected Telegram API call: {request.url.path}")


def make_hub_app(fake_api: FakeTelegramBotAPI, **kwargs):
    embodiment_app = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    core_app = create_core_app()
    telegram_client = TelegramClient("fake-token", transport=httpx.MockTransport(fake_api.handler))
    hub_app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        client_factory=lambda base_url: EmbodimentClient(base_url, transport=httpx.ASGITransport(app=embodiment_app)),
        companion_core_client=CompanionCoreClient(
            "http://companion-core", transport=httpx.ASGITransport(app=core_app)
        ),
        run_heartbeat_task=False,
        telegram_client=telegram_client,
        telegram_chat_registry=InMemoryTelegramChatRegistry(),
        telegram_default_user_id="hariz",
        **kwargs,
    )
    return hub_app


def test_telegram_disabled_by_default_without_a_token() -> None:
    app = create_app(
        registry=InMemoryRobotRegistry(),
        session_store=InMemorySessionStore(),
        companion_core_client=CompanionCoreClient("http://companion-core", transport=httpx.ASGITransport(app=create_core_app())),
        run_heartbeat_task=False,
        telegram_bot_token=None,
    )
    with TestClient(app) as client:
        # No crash, no Postgres needed for the (unused) telegram chat registry.
        resp = client.get("/health")
        assert resp.status_code == 200


def test_inbound_telegram_message_reaches_companion_core_and_gets_a_reply() -> None:
    fake_api = FakeTelegramBotAPI()
    fake_api.enqueue_text_message(chat_id=555, text="hello from telegram")
    hub_app = make_hub_app(fake_api, run_telegram_poll_task=True)

    with TestClient(hub_app):  # starts the telegram poll loop via lifespan
        deadline = time.monotonic() + 2.0
        while not fake_api.sent_messages and time.monotonic() < deadline:
            time.sleep(0.02)

    assert fake_api.sent_messages, "expected a reply to be sent back over Telegram"
    chat_id, text = fake_api.sent_messages[0]
    assert chat_id == 555
    assert "hello from telegram" in text


def test_start_on_reachy_continue_in_telegram() -> None:
    """Phase 7 exit criterion: start on Reachy, continue the same session
    in Telegram."""
    fake_api = FakeTelegramBotAPI()
    hub_app = make_hub_app(fake_api, run_telegram_poll_task=True)

    with TestClient(hub_app) as client:
        # "Start on Reachy": same user_id the Telegram poll loop will use.
        resp = client.post("/messages", json={"user_id": "hariz", "channel": "reachy", "text": "hi from reachy"})
        assert resp.status_code == 200
        started = resp.json()
        assert "turn 1" in started["reply"]

        # Now a real inbound Telegram message for the same (single) user.
        fake_api.enqueue_text_message(chat_id=777, text="continuing on telegram")
        deadline = time.monotonic() + 2.0
        while not fake_api.sent_messages and time.monotonic() < deadline:
            time.sleep(0.02)

        session = client.get("/sessions/hariz").json()

    assert session["session_id"] == started["session_id"]
    assert session["conversation_id"] == started["conversation_id"]
    assert session["active_channel"] == "telegram"
    assert fake_api.sent_messages
    _, reply_text = fake_api.sent_messages[0]
    assert "turn 2" in reply_text


def test_voice_note_without_text_is_skipped() -> None:
    fake_api = FakeTelegramBotAPI()
    fake_api.pending_updates.append({"update_id": 1, "message": {"chat": {"id": 1}, "voice": {"file_id": "abc"}}})
    fake_api.enqueue_text_message(chat_id=1, text="a real text message after the voice note")
    hub_app = make_hub_app(fake_api, run_telegram_poll_task=True)

    with TestClient(hub_app):
        deadline = time.monotonic() + 2.0
        while not fake_api.sent_messages and time.monotonic() < deadline:
            time.sleep(0.02)

    assert len(fake_api.sent_messages) == 1
    assert "a real text message" in fake_api.sent_messages[0][1]


def test_learned_chat_id_is_used_for_the_reply() -> None:
    fake_api = FakeTelegramBotAPI()
    fake_api.enqueue_text_message(chat_id=42424242, text="hi")
    hub_app = make_hub_app(fake_api, run_telegram_poll_task=True)

    with TestClient(hub_app):
        deadline = time.monotonic() + 2.0
        while not fake_api.sent_messages and time.monotonic() < deadline:
            time.sleep(0.02)

    assert fake_api.sent_messages[0][0] == 42424242
