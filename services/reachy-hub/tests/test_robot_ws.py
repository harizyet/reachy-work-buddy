"""Tests for the ADR 0019 hub-side WSS control connection (Phase 22's
first slice: auth, registration, generation fencing, heartbeat/ack).
Uses FastAPI's TestClient websocket support (in-process, no real
sockets/network) — a real Caddy/TLS/network pass is separate live
verification, not covered here. See HANDOVER.md's Phase 22 status.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_connection_manager import RobotConnectionManager
from reachy_hub.robot_credential_store import InMemoryRobotCredentialStore
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from starlette.websockets import WebSocketDisconnect

from shared.models.robot_ws import WSMessageType
from shared.protocols.robot_ws import PROTOCOL_VERSION, ROBOTS_CONNECT

ROBOT_ID = "nano-1"
TOKEN = "test-robot-token"


def make_client(
    *, credential_store: InMemoryRobotCredentialStore | None = None, **kwargs
) -> tuple[TestClient, InMemoryRobotCredentialStore, RobotConnectionManager]:
    credential_store = credential_store or InMemoryRobotCredentialStore()
    connection_manager = RobotConnectionManager()
    kwargs.setdefault("robot_ws_heartbeat_interval", 0.05)
    kwargs.setdefault("robot_ws_watchdog_timeout", 0.2)
    kwargs.setdefault("registry", InMemoryRobotRegistry())
    kwargs.setdefault("session_store", InMemorySessionStore())
    kwargs.setdefault("audit_log", InMemoryAuditLog())
    kwargs.setdefault("notification_queue", InMemoryNotificationQueue())
    app = create_app(
        robot_credential_store=credential_store,
        robot_connection_manager=connection_manager,
        run_heartbeat_task=False,
        run_telegram_poll_task=False,
        **kwargs,
    )
    return TestClient(app), credential_store, connection_manager


def register_headers(robot_id: str = ROBOT_ID, token: str = TOKEN) -> dict[str, str]:
    return {"X-Robot-Id": robot_id, "Authorization": f"Bearer {token}"}


def test_missing_credentials_closes_with_auth_failed() -> None:
    client, _, _ = make_client()
    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect(ROBOTS_CONNECT):
        pass
    assert excinfo.value.code == 4401


def test_wrong_token_closes_with_auth_failed() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, _ = make_client(credential_store=store)

    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect(ROBOTS_CONNECT, headers=register_headers(token="wrong")):
        pass
    assert excinfo.value.code == 4401


def test_unprovisioned_robot_id_closes_with_auth_failed() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, _ = make_client(credential_store=store)

    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect(ROBOTS_CONNECT, headers=register_headers(robot_id="someone-else")):
        pass
    assert excinfo.value.code == 4401


def test_successful_registration_receives_generation() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, manager = make_client(credential_store=store)

    with client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws:
        ws.send_json(
            {"type": WSMessageType.REGISTER, "robot_id": ROBOT_ID, "protocol_version": PROTOCOL_VERSION, "capabilities": ["move", "camera"], "sim": False}
        )
        reply = ws.receive_json()
        assert reply["type"] == WSMessageType.REGISTERED
        assert reply["robot_id"] == ROBOT_ID
        assert reply["generation"] == 1
        assert manager.is_online(ROBOT_ID)
        assert manager.get(ROBOT_ID).capabilities == ["move", "camera"]


def test_registration_identity_mismatch_is_rejected() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, manager = make_client(credential_store=store)

    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws:
        ws.send_json(
            {"type": WSMessageType.REGISTER, "robot_id": "a-different-robot", "protocol_version": PROTOCOL_VERSION}
        )
        ws.receive_json()  # the ErrorMessage
        ws.receive_json()  # blocks until the close arrives
    assert excinfo.value.code == 4422
    assert not manager.is_online(ROBOT_ID)


def test_registration_version_mismatch_is_rejected() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, manager = make_client(credential_store=store)

    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws:
        ws.send_json({"type": WSMessageType.REGISTER, "robot_id": ROBOT_ID, "protocol_version": PROTOCOL_VERSION + 1})
        ws.receive_json()
        ws.receive_json()
    assert excinfo.value.code == 4400
    assert not manager.is_online(ROBOT_ID)


def test_malformed_registration_is_rejected() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, _ = make_client(credential_store=store)

    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws:
        ws.send_json({"not": "a valid register message"})
        ws.receive_json()
        ws.receive_json()
    assert excinfo.value.code == 4422


def test_second_connection_fences_out_the_first() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, manager = make_client(credential_store=store)

    with client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws1:
        ws1.send_json({"type": WSMessageType.REGISTER, "robot_id": ROBOT_ID, "protocol_version": PROTOCOL_VERSION})
        first = ws1.receive_json()
        assert first["generation"] == 1

        with client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws2:
            ws2.send_json({"type": WSMessageType.REGISTER, "robot_id": ROBOT_ID, "protocol_version": PROTOCOL_VERSION})
            second = ws2.receive_json()
            assert second["generation"] == 2

            # The first connection must now have been closed by the hub
            # (fenced out) — code 4409, ADR 0019's generation fencing.
            # ws1 may receive an ordinary HEARTBEAT first if the fencing
            # close hasn't propagated yet; drain until the disconnect.
            with pytest.raises(WebSocketDisconnect) as excinfo:
                while True:
                    ws1.receive_json()
            assert excinfo.value.code == 4409

            # Only the newer generation is tracked as online.
            assert manager.get(ROBOT_ID).generation == 2


def test_heartbeat_sent_periodically_and_acked() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, _ = make_client(credential_store=store, robot_ws_heartbeat_interval=0.05, robot_ws_watchdog_timeout=1.0)

    with client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws:
        ws.send_json({"type": WSMessageType.REGISTER, "robot_id": ROBOT_ID, "protocol_version": PROTOCOL_VERSION})
        ws.receive_json()  # REGISTERED

        heartbeat = ws.receive_json()
        assert heartbeat["type"] == WSMessageType.HEARTBEAT
        ws.send_json({"type": WSMessageType.HEARTBEAT_ACK})


def test_watchdog_closes_connection_after_silence() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    # Heartbeats sent, but this test never acks or sends anything back —
    # the watchdog must still close the connection once watchdog_timeout
    # elapses with nothing received.
    client, _, manager = make_client(credential_store=store, robot_ws_heartbeat_interval=0.05, robot_ws_watchdog_timeout=0.15)

    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws:
        ws.send_json({"type": WSMessageType.REGISTER, "robot_id": ROBOT_ID, "protocol_version": PROTOCOL_VERSION})
        ws.receive_json()  # REGISTERED
        while True:
            ws.receive_json()  # keep draining heartbeats until the watchdog fires
    assert excinfo.value.code == 4408
    assert not manager.is_online(ROBOT_ID)


def test_disconnect_without_fencing_removes_the_connection() -> None:
    store = InMemoryRobotCredentialStore()
    store.provision(ROBOT_ID, TOKEN)
    client, _, manager = make_client(credential_store=store)

    with client.websocket_connect(ROBOTS_CONNECT, headers=register_headers()) as ws:
        ws.send_json({"type": WSMessageType.REGISTER, "robot_id": ROBOT_ID, "protocol_version": PROTOCOL_VERSION})
        ws.receive_json()
        assert manager.is_online(ROBOT_ID)

    assert not manager.is_online(ROBOT_ID)


class _FakeSocket:
    def __init__(self) -> None:
        self.closed_with: int | None = None

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


async def _run_manager_scenario() -> None:
    manager = RobotConnectionManager()
    first_socket = _FakeSocket()
    first = await manager.register("r1", first_socket, capabilities=[], sim=True)
    assert first.generation == 1

    second_socket = _FakeSocket()
    second = await manager.register("r1", second_socket, capabilities=[], sim=True)
    assert second.generation == 2
    assert first_socket.closed_with == 4409

    # An old, already-fenced generation's unregister call must not remove
    # the newer connection.
    await manager.unregister("r1", first.generation)
    assert manager.is_online("r1")
    assert manager.get("r1").generation == 2

    await manager.unregister("r1", second.generation)
    assert not manager.is_online("r1")


def test_connection_manager_fencing_and_stale_unregister_is_noop() -> None:
    asyncio.run(_run_manager_scenario())
