"""29.27 restart recovery plus the durable-usage and allowance behaviour that
rides on it. A "restart" is a fresh supervisor/provider/runtime view over the
same store; the container runtime stands in for Docker's own surviving state.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from coding_agent_service.app import create_app
from coding_agent_service.claude_provider import ClaudeCodeProvider
from coding_agent_service.credentials import InMemoryCredentialStore
from coding_agent_service.providers import ProviderError, SimulatedProvider
from coding_agent_service.reconcile import recover_sessions
from coding_agent_service.runtime import (
    ContainerRuntimeError,
    ContainerSpec,
    DockerCLIContainerRuntime,
    SimulatedContainerRuntime,
)
from coding_agent_service.service import CodingAgentSupervisor
from coding_agent_service.store import InMemoryCodingAgentStore
from fastapi.testclient import TestClient

from shared.models.coding_agent import (
    CodingAgentSession,
    CodingAgentStatus,
    CodingProject,
    UsageDimension,
    UsageSnapshot,
)

TOKEN = "recovery-token"
HEADERS = {"X-Reachy-Coding-Agent-Service-Token": TOKEN}

RESULT_LINE = {
    "type": "result", "subtype": "success", "is_error": False, "session_id": "claude-1",
    "result": "All done.", "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.01,
}


def _jsonl(*lines) -> str:
    return "\n".join(json.dumps(line) for line in lines)


def _rate_limit(kind: str, utilization: float, resets_at: float) -> dict:
    # Shape taken from the installed Claude CLI binary; no live event captured yet.
    return {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "allowed_warning", "rateLimitType": kind,
            "utilization": utilization, "resetsAt": resets_at,
        },
    }


class UnreachableDocker(SimulatedContainerRuntime):
    async def list_labeled(self):
        raise ContainerRuntimeError("docker daemon not reachable")


class Harness:
    def __init__(self) -> None:
        self.store = InMemoryCodingAgentStore()
        self.runtime = SimulatedContainerRuntime()
        self.credentials = InMemoryCredentialStore()
        self.claude = ClaudeCodeProvider(self.runtime, self.credentials, self.store)
        self.providers = {"simulated": SimulatedProvider(), "claude-code": self.claude}
        self.supervisor = CodingAgentSupervisor(self.store, self.providers)

    async def project(self, provider: str = "claude-code") -> CodingProject:
        return await self.store.add_project(CodingProject(name="P", repository_path="/p", provider=provider))

    async def claude_session(self, *, status=CodingAgentStatus.RUNNING, container: bool = True) -> CodingAgentSession:
        project = await self.project()
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

    async def recover(self, runtime=None):
        return await recover_sessions(self.supervisor, self.store, runtime or self.runtime)


def run(coro):
    return asyncio.run(coro)


def test_running_container_keeps_session_running() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        report = await h.recover()
        assert report.unchanged == [session.id]
        assert (await h.store.get_session(session.id)).status == CodingAgentStatus.RUNNING

    run(go())


def test_container_that_finished_while_service_was_down_is_completed() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        h.runtime.set_logs(session.container_id, _jsonl(RESULT_LINE))
        await h.runtime.stop(session.container_id)
        report = await h.recover()
        assert report.changed == [session.id]
        stored = await h.store.get_session(session.id)
        assert stored.status == CodingAgentStatus.COMPLETED
        assert stored.completed_at is not None
        # Final usage is persisted so it outlives the container's logs.
        assert (await h.store.latest_usage_snapshot(session.id)).dimensions

    run(go())


def test_container_gone_with_no_result_is_lost_not_completed() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        h.runtime = SimulatedContainerRuntime()  # Docker no longer knows the container
        h.claude._runtime = h.runtime
        report = await h.recover()
        assert report.changed == [session.id]
        stored = await h.store.get_session(session.id)
        assert stored.status == CodingAgentStatus.LOST
        assert "no longer exists" in stored.last_event

    run(go())


def test_unreachable_docker_changes_nothing() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        report = await h.recover(UnreachableDocker())
        assert report.skipped_reason and "not reachable" in report.skipped_reason
        assert (await h.store.get_session(session.id)).status == CodingAgentStatus.RUNNING

    run(go())


def test_terminal_sessions_are_never_revisited() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session(status=CodingAgentStatus.COMPLETED, container=False)
        report = await h.recover()
        assert report.changed == report.unchanged == []
        assert (await h.store.get_session(session.id)).status == CodingAgentStatus.COMPLETED

    run(go())


def test_session_without_container_id_adopts_the_labeled_container() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session(container=False)
        container_id = await h.runtime.start(ContainerSpec(
            image="x", project_id=session.project_id, session_id=session.id, provider="claude-code",
            host_mount_path="/p",
        ))
        report = await h.recover()
        stored = await h.store.get_session(session.id)
        assert report.changed == [session.id]
        assert stored.container_id == container_id
        assert stored.status == CodingAgentStatus.RUNNING

    run(go())


def test_session_with_no_container_anywhere_is_lost() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session(container=False)
        await h.recover()
        assert (await h.store.get_session(session.id)).status == CodingAgentStatus.LOST

    run(go())


def test_simulated_session_waiting_on_the_owner_is_left_alone() -> None:
    async def go() -> None:
        h = Harness()
        project = await h.project("simulated")
        waiting = await h.supervisor.start_session(
            project_id=project.id, task_summary="ask: pick one", owner_user_id="owner-1"
        )
        assert waiting.status == CodingAgentStatus.WAITING_FOR_INPUT
        report = await h.recover()
        assert report.unchanged == [waiting.id]
        assert (await h.store.get_session(waiting.id)).status == CodingAgentStatus.WAITING_FOR_INPUT

    run(go())


def test_unregistered_provider_is_left_as_recorded_and_reported() -> None:
    async def go() -> None:
        h = Harness()
        project = await h.project("codex")
        session = CodingAgentSession(
            project_id=project.id, provider="codex", status=CodingAgentStatus.RUNNING,
            task_summary="x", owner_user_id="owner-1",
        )
        await h.store.add_session(session)
        report = await h.recover()
        assert report.unresolved == [session.id]
        assert (await h.store.get_session(session.id)).status == CodingAgentStatus.RUNNING

    run(go())


def test_one_failing_inspection_does_not_stop_the_others() -> None:
    async def go() -> None:
        h = Harness()
        broken = await h.claude_session()
        healthy = await h.claude_session()

        original = h.claude.inspect_session

        async def flaky(session):
            if session.id == broken.id:
                raise RuntimeError("boom")
            return await original(session)

        h.claude.inspect_session = flaky
        report = await h.recover()
        assert report.unresolved == [broken.id]
        assert report.unchanged == [healthy.id]

    run(go())


def test_orphan_labeled_containers_are_reported_not_touched() -> None:
    async def go() -> None:
        h = Harness()
        orphan = await h.runtime.start(ContainerSpec(
            image="x", project_id="p", session_id="unknown-session", provider="claude-code", host_mount_path="/p",
        ))
        report = await h.recover()
        assert report.orphan_container_ids == [orphan]
        assert await h.runtime.status(orphan) is not None

    run(go())


def test_recovery_is_idempotent() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        await h.runtime.stop(session.container_id)
        first = await h.recover()
        second = await h.recover()
        assert first.changed == [session.id]
        assert second.changed == second.unchanged == []

    run(go())


# --- usage persistence and allowance ---------------------------------------


def test_final_usage_outlives_the_container_logs() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        h.runtime.set_logs(session.container_id, _jsonl(RESULT_LINE))
        await h.runtime.stop(session.container_id)
        await h.recover()

        h.runtime._logs.clear()  # container removed; its logs are gone
        usage = await h.supervisor.collect_usage(session.id)
        assert {d.name: d.value for d in usage.dimensions}["input_tokens"] == 10

    run(go())


def test_allowance_reports_only_windows_that_have_not_reset() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        now = datetime.now(UTC)
        future = (now + timedelta(hours=2)).timestamp()
        past = (now - timedelta(hours=1)).timestamp()
        h.runtime.set_logs(session.container_id, _jsonl(
            _rate_limit("five_hour", 0.87, future),
            _rate_limit("seven_day", 0.4, past),
            RESULT_LINE,
        ))
        await h.runtime.stop(session.container_id)
        await h.recover()

        allowance = await h.supervisor.provider_allowance("claude-code")
        assert [(w.name, w.value, w.unit) for w in allowance.windows] == [("five_hour_window", 87.0, "%")]
        assert allowance.windows[0].resets_at > now

    run(go())


def test_allowance_is_empty_when_the_cli_reported_no_utilization() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        info = {"status": "allowed", "rateLimitType": "five_hour", "resetsAt": datetime.now(UTC).timestamp() + 600}
        h.runtime.set_logs(session.container_id, _jsonl({"type": "rate_limit_event", "rate_limit_info": info}, RESULT_LINE))
        await h.runtime.stop(session.container_id)
        await h.recover()
        assert (await h.supervisor.provider_allowance("claude-code")).windows == []

    run(go())


def test_malformed_rate_limit_events_are_ignored() -> None:
    async def go() -> None:
        h = Harness()
        session = await h.claude_session()
        future = datetime.now(UTC).timestamp() + 600
        h.runtime.set_logs(session.container_id, _jsonl(
            _rate_limit("five_hour", True, future),
            _rate_limit("five_hour", "0.5", future),
            _rate_limit("something_new", 0.5, future),
            _rate_limit("five_hour", 0.5, "soon"),
            {"type": "rate_limit_event", "rate_limit_info": "bad"},
        ))
        usage = await h.claude.collect_usage(await h.store.get_session(session.id))
        assert usage.dimensions == []

    run(go())


def test_allowance_route_and_unknown_provider() -> None:
    store = InMemoryCodingAgentStore()
    providers = {"simulated": SimulatedProvider()}
    app = create_app(store=store, providers=providers, service_token=TOKEN)
    with TestClient(app) as client:
        ok = client.get("/providers/simulated/allowance", headers=HEADERS)
        assert ok.status_code == 200
        assert ok.json() == {"provider": "simulated", "windows": []}
        assert client.get("/providers/nope/allowance", headers=HEADERS).status_code == 404
        assert client.get("/providers/simulated/allowance").status_code in (401, 403)


# --- start failure ---------------------------------------------------------


def test_failed_start_leaves_a_failed_session_not_a_starting_zombie() -> None:
    class BrokenProvider(SimulatedProvider):
        async def start_session(self, session):
            raise ProviderError("no credential configured")

    async def go() -> None:
        store = InMemoryCodingAgentStore()
        supervisor = CodingAgentSupervisor(store, {"simulated": BrokenProvider()})
        project = await supervisor.add_project(CodingProject(name="P", repository_path="/p", provider="simulated"))
        with pytest.raises(ProviderError):
            await supervisor.start_session(project_id=project.id, task_summary="x", owner_user_id="owner-1")
        [session] = await store.list_sessions()
        assert session.status == CodingAgentStatus.FAILED
        assert "no credential configured" in session.last_event

    run(go())


# --- lifespan --------------------------------------------------------------


class RecordingDurableStore(InMemoryCodingAgentStore):
    durable = True

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def open(self) -> None:
        self.calls.append("open")

    async def close(self) -> None:
        self.calls.append("close")


def test_lifespan_opens_recovers_and_closes_a_durable_store() -> None:
    async def seed(store, runtime) -> CodingAgentSession:
        project = await store.add_project(CodingProject(name="P", repository_path="/p", provider="claude-code"))
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", status=CodingAgentStatus.RUNNING,
            task_summary="x", owner_user_id="owner-1", container_id="vanished",
        )
        await store.add_session(session)
        return session

    store = RecordingDurableStore()
    runtime = SimulatedContainerRuntime()
    session = run(seed(store, runtime))
    app = create_app(store=store, service_token=TOKEN, container_runtime=runtime,
                     credential_store=InMemoryCredentialStore())
    with TestClient(app) as client:
        body = client.get(f"/sessions/{session.id}", headers=HEADERS).json()
        assert body["status"] == "lost"
    assert store.calls == ["open", "close"]


def test_lifespan_skips_recovery_for_an_in_memory_store() -> None:
    store = InMemoryCodingAgentStore()
    app = create_app(store=store, service_token=TOKEN, container_runtime=UnreachableDocker(),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app):
        assert not hasattr(app.state, "recovery_report")


def test_usage_snapshot_dedup_and_fallback_on_in_memory_store() -> None:
    async def go() -> None:
        store = InMemoryCodingAgentStore()
        snap = UsageSnapshot(
            session_id="s1", provider="simulated",
            dimensions=[UsageDimension(name="input_tokens", value=3, unit="tokens")],
        )
        await store.add_usage_snapshot(snap)
        assert (await store.latest_usage_snapshot("s1")).dimensions == snap.dimensions
        assert await store.latest_usage_snapshot("other") is None
        assert [s.session_id for s in await store.recent_usage_snapshots("simulated", 5)] == ["s1"]

    run(go())


@pytest.mark.skipif(
    os.environ.get("CODING_AGENT_DOCKER_TEST") != "1",
    reason="requires explicit opt-in (CODING_AGENT_DOCKER_TEST=1) and a local Docker daemon",
)
def test_recovery_against_real_docker_labels() -> None:
    """A brand-new runtime/supervisor (the restarted service) finds a real
    labeled container from Docker alone, adopts it for a record that never
    stored its id, and reports LOST once the container is really removed."""

    async def go() -> None:
        runtime = DockerCLIContainerRuntime()
        h = Harness()
        h.runtime = runtime
        h.claude = ClaudeCodeProvider(runtime, h.credentials, h.store)
        h.supervisor = CodingAgentSupervisor(h.store, {"simulated": SimulatedProvider(), "claude-code": h.claude})
        session = await h.claude_session(container=False)
        container_id = await runtime.start(ContainerSpec(
            image="busybox:latest", project_id=session.project_id, session_id=session.id,
            provider="claude-code", host_mount_path="/tmp", command=["sleep", "60"], network_profile="offline",
        ))
        try:
            report = await recover_sessions(h.supervisor, h.store, DockerCLIContainerRuntime())
            stored = await h.store.get_session(session.id)
            assert report.changed == [session.id]
            assert stored.container_id == container_id
            assert stored.status == CodingAgentStatus.RUNNING
        finally:
            proc = await asyncio.create_subprocess_exec("docker", "rm", "-f", container_id)
            await proc.wait()

        await recover_sessions(h.supervisor, h.store, DockerCLIContainerRuntime())
        assert (await h.store.get_session(session.id)).status == CodingAgentStatus.LOST

    asyncio.run(go())
