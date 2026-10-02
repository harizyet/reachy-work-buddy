"""Background polling of in-flight sessions (completion without /refresh)."""

import asyncio
import json

from coding_agent_service.claude_provider import ClaudeCodeProvider
from coding_agent_service.credentials import InMemoryCredentialStore
from coding_agent_service.providers import SimulatedProvider
from coding_agent_service.runtime import (
    ContainerRuntimeError,
    ContainerSpec,
    SimulatedContainerRuntime,
)
from coding_agent_service.service import CodingAgentSupervisor
from coding_agent_service.session_poller import poll_once, run_poll_loop
from coding_agent_service.store import InMemoryCodingAgentStore

from shared.models.coding_agent import (
    CodingAgentEventType,
    CodingAgentSession,
    CodingAgentStatus,
    CodingProject,
)

RESULT_LINE = {
    "type": "result", "subtype": "success", "is_error": False, "session_id": "claude-1",
    "result": "All done.", "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.01,
}


def _jsonl(*lines) -> str:
    return "\n".join(json.dumps(line) for line in lines)


class Harness:
    def __init__(self) -> None:
        self.store = InMemoryCodingAgentStore()
        self.runtime = SimulatedContainerRuntime()
        self.claude = ClaudeCodeProvider(self.runtime, InMemoryCredentialStore(), self.store)
        self.supervisor = CodingAgentSupervisor(
            self.store, {"simulated": SimulatedProvider(), "claude-code": self.claude}
        )

    async def claude_session(self, *, status=CodingAgentStatus.RUNNING, container: bool = True):
        project = await self.store.add_project(
            CodingProject(name="P", repository_path="/p", provider="claude-code")
        )
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", status=status, task_summary="work",
            owner_user_id="owner-1", provider_session_id="claude-1",
        )
        if container:
            session.container_id = await self.runtime.start(ContainerSpec(
                image="x", project_id=project.id, session_id=session.id, provider="claude-code",
                host_mount_path="/p",
            ))
        await self.store.add_session(session)
        return session


def run(coro):
    return asyncio.run(coro)


def test_finished_container_becomes_completed_and_is_recorded() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        h.runtime.set_logs(session.container_id, _jsonl(RESULT_LINE))
        await h.runtime.stop(session.container_id)
        assert await poll_once(h.supervisor, h.store) == [session.id]
        stored = await h.store.get_session(session.id)
        assert stored.status == CodingAgentStatus.COMPLETED
        assert stored.completed_at is not None
        # A second tick has nothing left to do.
        assert await poll_once(h.supervisor, h.store) == []

    run(go())


def test_unchanged_running_session_records_no_event() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        before = len(await h.store.list_events(session.id))
        assert await poll_once(h.supervisor, h.store) == []
        assert await poll_once(h.supervisor, h.store) == []
        assert len(await h.store.list_events(session.id)) == before

    run(go())


def test_waiting_terminal_and_containerless_sessions_are_skipped() -> None:
    async def go() -> None:
        h = Harness()
        waiting = await h.claude_session(status=CodingAgentStatus.WAITING_FOR_INPUT)
        done = await h.claude_session(status=CodingAgentStatus.COMPLETED)
        starting = await h.claude_session(status=CodingAgentStatus.STARTING, container=False)
        h.runtime.set_logs(waiting.container_id, _jsonl(RESULT_LINE))
        await h.runtime.stop(waiting.container_id)
        assert await poll_once(h.supervisor, h.store) == []
        assert (await h.store.get_session(waiting.id)).status == CodingAgentStatus.WAITING_FOR_INPUT
        assert (await h.store.get_session(done.id)).status == CodingAgentStatus.COMPLETED
        assert (await h.store.get_session(starting.id)).status == CodingAgentStatus.STARTING

    run(go())


def test_one_failing_inspection_does_not_stop_the_others() -> None:
    async def go() -> None:
        h = Harness()
        broken = await h.claude_session()
        good = await h.claude_session()
        h.runtime.set_logs(good.container_id, _jsonl(RESULT_LINE))
        await h.runtime.stop(good.container_id)
        original = h.runtime.status

        async def flaky(container_id: str):
            if container_id == broken.container_id:
                raise RuntimeError("docker hiccup")
            return await original(container_id)

        h.runtime.status = flaky
        assert await poll_once(h.supervisor, h.store) == [good.id]
        assert (await h.store.get_session(broken.id)).status == CodingAgentStatus.RUNNING

    run(go())


def test_gone_container_is_lost_never_completed() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        h.runtime._status.pop(session.container_id)
        await poll_once(h.supervisor, h.store)
        assert (await h.store.get_session(session.id)).status == CodingAgentStatus.LOST

    run(go())


def test_loop_polls_each_interval_and_survives_an_error() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        sleeps: list[float] = []

        async def controlled_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 1:
                # Finish the container between the first and second tick.
                h.runtime.set_logs(session.container_id, _jsonl(RESULT_LINE))
                await h.runtime.stop(session.container_id)
            if len(sleeps) == 3:
                raise asyncio.CancelledError

        calls = {"n": 0}
        original = h.store.list_sessions

        async def sometimes_failing():
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("db blip")
            return await original()

        h.store.list_sessions = sometimes_failing
        try:
            await run_poll_loop(h.supervisor, h.store, 30, controlled_sleep)
        except asyncio.CancelledError:
            pass
        assert sleeps == [30, 30, 30]
        # Tick 2 errored; tick 3 saw the finished container.
        assert (await original())[0].status == CodingAgentStatus.COMPLETED

    run(go())


def test_completion_event_is_the_one_notifications_rely_on() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        h.runtime.set_logs(session.container_id, _jsonl(RESULT_LINE))
        await h.runtime.stop(session.container_id)
        await poll_once(h.supervisor, h.store)
        types = [e.type for e in await h.store.list_events(session.id)]
        assert CodingAgentEventType.AGENT_COMPLETED in types

    run(go())


def test_unreachable_docker_keeps_sessions_as_recorded() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()

        async def refuse(_id: str):
            raise ContainerRuntimeError("docker daemon not reachable")

        h.runtime.status = refuse
        assert await poll_once(h.supervisor, h.store) == []
        assert (await h.store.get_session(session.id)).status == CodingAgentStatus.RUNNING

    run(go())


def test_service_lifespan_runs_the_poller_and_stops_it() -> None:
    import time

    from coding_agent_service.app import create_app
    from fastapi.testclient import TestClient

    h = Harness()
    session = asyncio.run(h.claude_session())
    h.runtime.set_logs(session.container_id, _jsonl(RESULT_LINE))
    asyncio.run(h.runtime.stop(session.container_id))
    app = create_app(
        store=h.store, providers={"claude-code": h.claude}, service_token="t",
        container_runtime=h.runtime, poll_interval_seconds=0.02,
    )
    with TestClient(app):
        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline:
            status = asyncio.run(h.store.get_session(session.id)).status
            if status == CodingAgentStatus.COMPLETED:
                break
            time.sleep(0.02)
    assert status == CodingAgentStatus.COMPLETED
