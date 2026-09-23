"""Tests for RobotWSClient against a real local `websockets.serve` test
server — a genuine end-to-end WS round trip (not mocked), just not
against the actual reachy-hub FastAPI server or a real network. See
robot_ws_client.py's docstring: this is Phase 22's first slice
(connectivity only), not yet verified against a live hub.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
import websockets
from reachy_embodiment.robot_ws_client import RobotWSClient, _as_ws_url, next_backoff

from shared.models.robot_ws import WSMessageType
from shared.protocols.robot_ws import PROTOCOL_VERSION


def test_as_ws_url_derives_scheme_from_http_https() -> None:
    assert _as_ws_url("http://hub.example:8080/hub") == "ws://hub.example:8080/hub"
    assert _as_ws_url("https://hub.example/hub") == "wss://hub.example/hub"
    assert _as_ws_url("ws://hub.example/hub") == "ws://hub.example/hub"


def test_client_derives_ws_url_from_configured_http_hub_url() -> None:
    client = RobotWSClient("http://hub.example:8080/hub", "nano-1", "tok")
    assert client._hub_ws_url.startswith("ws://hub.example:8080/hub")


def test_next_backoff_doubles_and_caps_at_30() -> None:
    sequence = [1.0]
    for _ in range(6):
        sequence.append(next_backoff(sequence[-1]))
    assert sequence == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


@contextlib.asynccontextmanager
async def _serve(handler):
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


async def _accept_and_register(ws, *, generation: int = 1) -> dict:
    raw = await ws.recv()
    register = json.loads(raw)
    await ws.send(json.dumps({"type": WSMessageType.REGISTERED, "robot_id": register["robot_id"], "generation": generation}))
    return register


def test_client_registers_and_reports_connected() -> None:
    registered = asyncio.Event()

    async def handler(ws):
        await _accept_and_register(ws)
        registered.set()
        await ws.wait_closed()

    async def scenario():
        async with _serve(handler) as url:
            client = RobotWSClient(url, "nano-1", "tok", capabilities=["move"], sim=True)
            task = asyncio.create_task(client.run())
            try:
                await asyncio.wait_for(registered.wait(), timeout=2.0)
                await asyncio.sleep(0.05)  # let the client-side state update after recv
                assert client.connected is True
                assert client.generation == 1
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


def test_client_responds_to_heartbeat_with_ack() -> None:
    got_ack = asyncio.Event()

    async def handler(ws):
        await _accept_and_register(ws)
        await ws.send(json.dumps({"type": WSMessageType.HEARTBEAT}))
        raw = await ws.recv()
        message = json.loads(raw)
        assert message["type"] == WSMessageType.HEARTBEAT_ACK
        got_ack.set()
        await ws.wait_closed()

    async def scenario():
        async with _serve(handler) as url:
            client = RobotWSClient(url, "nano-1", "tok")
            task = asyncio.create_task(client.run())
            try:
                await asyncio.wait_for(got_ack.wait(), timeout=2.0)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


def test_client_sends_correct_register_fields() -> None:
    async def handler(ws, received: asyncio.Future):
        raw = await ws.recv()
        received.set_result(json.loads(raw))
        await ws.send(json.dumps({"type": WSMessageType.REGISTERED, "robot_id": "nano-1", "generation": 1}))
        await ws.wait_closed()

    async def scenario():
        received = asyncio.get_running_loop().create_future()

        async def bound_handler(ws):
            await handler(ws, received)

        async with _serve(bound_handler) as url:
            client = RobotWSClient(url, "nano-1", "secret-tok", capabilities=["move", "camera"], sim=True)
            task = asyncio.create_task(client.run())
            try:
                register = await asyncio.wait_for(received, timeout=2.0)
                assert register["type"] == WSMessageType.REGISTER
                assert register["robot_id"] == "nano-1"
                assert register["protocol_version"] == PROTOCOL_VERSION
                assert register["capabilities"] == ["move", "camera"]
                assert register["sim"] is True
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


def test_client_reconnects_after_server_closes_connection() -> None:
    connection_count = 0
    second_registered = asyncio.Event()

    async def handler(ws):
        nonlocal connection_count
        connection_count += 1
        await _accept_and_register(ws, generation=connection_count)
        if connection_count == 1:
            await ws.close()  # simulate a dropped connection
        else:
            second_registered.set()
            await ws.wait_closed()

    async def scenario():
        async with _serve(handler) as url:
            client = RobotWSClient(url, "nano-1", "tok")
            task = asyncio.create_task(client.run())
            try:
                # Backoff starts at 1s; give it comfortable room to
                # reconnect without asserting an exact timing bound.
                await asyncio.wait_for(second_registered.wait(), timeout=5.0)
                await asyncio.sleep(0.05)  # let the client finish processing REGISTERED before asserting
                assert connection_count == 2
                assert client.generation == 2
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


def test_client_task_exits_cleanly_on_cancel() -> None:
    async def handler(ws):
        await _accept_and_register(ws)
        await ws.wait_closed()

    async def scenario():
        async with _serve(handler) as url:
            client = RobotWSClient(url, "nano-1", "tok")
            task = asyncio.create_task(client.run())
            await asyncio.sleep(0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
