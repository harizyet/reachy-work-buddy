"""The MinerU server dying (for example OOM-killed under the container's memory limit) while the worker process stays up: the worker restarts it itself,
and never starts or resets a parse while the backend is not ready (that would be recorded by MinerU as a failed parse of the document's bytes)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from document_worker.engine import DoclibEngine, EngineError


class DeadError(Exception):
    code = "server_not_running"


class FakeClient:
    """Stands in for DoclibClient: a server that is up or down, and a record of every parse started."""

    def __init__(self, up: bool = True, parse_server_healthy: bool = True, restarts: int = 0, managed_running: bool = True) -> None:
        self.up, self.healthy, self.parses, self.restarts, self.managed_running = up, parse_server_healthy, [], restarts, managed_running

    def get_server_status(self):
        if not self.up:
            raise DeadError()
        return SimpleNamespace(running=True, parse_server=SimpleNamespace(local=SimpleNamespace(healthy=self.healthy, restart_count=self.restarts, max_restart_attempts=3, managed_running=self.managed_running)))

    def get_telemetry_status(self):
        return SimpleNamespace(state="disabled")

    def ensure_parse(self, request):
        self.parses.append(request)
        return SimpleNamespace(sha256="a" * 64, short_id="aaaaaaa")

    def get_doc(self, ref, **kw):
        if not self.up:
            raise DeadError()
        return SimpleNamespace(page_count=1)


def engine_with(client: FakeClient, **kw) -> DoclibEngine:
    engine = DoclibEngine(**kw)
    engine._api = lambda: client  # the real one builds a new client after a failure; here the fake server comes and goes by itself
    return engine


def settle(engine: DoclibEngine) -> None:
    deadline = time.monotonic() + 5
    while engine._recovering and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not engine._recovering


def test_a_dead_server_found_by_the_health_check_is_started_again_once_per_interval(monkeypatch) -> None:
    client = FakeClient(up=False)
    engine = engine_with(client, recovery_interval=60)
    started = []

    def start():
        started.append(1)
        client.up = True

    monkeypatch.setattr(engine, "start", start)
    first = engine.health()
    assert not first.ready and first.detail == "server_not_running"  # the check itself answers at once
    settle(engine)
    assert started == [1] and engine.health().ready
    client.up = False
    engine.health()
    settle(engine)
    assert started == [1]  # rate limited: a second death inside the interval waits for the next one


def test_recovery_runs_one_at_a_time_and_never_blocks_the_caller(monkeypatch) -> None:
    client = FakeClient(up=False)
    engine = engine_with(client, recovery_interval=0)
    gate, entered, count = threading.Event(), threading.Event(), []

    def slow_start():
        count.append(1)
        entered.set()
        gate.wait(5)

    monkeypatch.setattr(engine, "start", slow_start)
    t0 = time.monotonic()
    for _ in range(5):
        engine.health()
    assert time.monotonic() - t0 < 1  # nothing waited for the restart
    assert entered.wait(5)
    assert count == [1]  # five health checks during one restart start one
    gate.set()
    settle(engine)


def test_a_failed_restart_is_logged_and_tried_again_after_the_interval(monkeypatch) -> None:
    client = FakeClient(up=False)
    engine = engine_with(client, recovery_interval=0)
    attempts = []

    def failing_start():
        attempts.append(1)
        raise EngineError("engine_unavailable")

    monkeypatch.setattr(engine, "start", failing_start)
    engine.health()
    settle(engine)
    engine.health()
    settle(engine)
    assert len(attempts) == 2 and not engine.health().ready


def test_a_call_that_fails_because_the_server_is_gone_triggers_the_restart_and_still_raises(monkeypatch) -> None:
    client = FakeClient(up=False)
    engine = engine_with(client, recovery_interval=60)
    monkeypatch.setattr(engine, "start", lambda: setattr(client, "up", True))
    with pytest.raises(EngineError) as raised:
        engine.page_count("aaaaaaa")
    assert raised.value.code == "server_not_running"
    settle(engine)
    assert engine.page_count("aaaaaaa") == 1


def test_a_parse_is_never_started_while_the_backend_is_down_or_warming_up() -> None:
    for client in (FakeClient(up=False), FakeClient(up=True, parse_server_healthy=False)):
        engine = engine_with(client, recovery_interval=3600)
        engine._last_recovery = time.monotonic()  # no restart attempt in this test
        with pytest.raises(EngineError) as raised:
            engine.ensure_parse(Path("/tmp/x.pdf"), "basic", None, False)
        assert raised.value.code == "engine_unavailable"
        assert client.parses == []  # nothing reached MinerU, so nothing is cached as failed


def test_a_parse_server_mineru_gave_up_on_is_fixed_by_restarting_the_server_not_left_dead(monkeypatch) -> None:
    # after repeated OOM kills MinerU stops restarting the parse server ("failed 3 restarts, disabling") and the doclib server stays up
    client = FakeClient(parse_server_healthy=False, restarts=3, managed_running=False)
    engine = engine_with(client, restart_interval=300)
    ran = []
    monkeypatch.setattr("document_worker.engine.subprocess.run", lambda cmd, **kw: ran.append(cmd))

    def start():
        client.healthy, client.restarts, client.managed_running = True, 0, True

    monkeypatch.setattr(engine, "start", start)
    assert not engine.health().ready
    settle(engine)
    assert ran == [["mineru", "server", "restart"]] and engine.health().ready
    client.healthy, client.restarts, client.managed_running = False, 3, False
    engine.health()
    settle(engine)
    assert len(ran) == 1  # at most one restart per interval, so an under-sized container cannot loop


def test_a_parse_server_that_is_only_warming_up_or_still_being_restarted_by_mineru_is_left_alone(monkeypatch) -> None:
    ran = []
    monkeypatch.setattr("document_worker.engine.subprocess.run", lambda cmd, **kw: ran.append(cmd))
    for client in (FakeClient(parse_server_healthy=False, restarts=0, managed_running=False), FakeClient(parse_server_healthy=False, restarts=3, managed_running=True),
                   FakeClient(parse_server_healthy=False, restarts=2, managed_running=False)):
        engine = engine_with(client, restart_interval=0)
        monkeypatch.setattr(engine, "start", lambda: None)
        assert not engine.health().ready
        settle(engine)
    assert ran == []
