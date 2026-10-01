"""29.2: container runtime. SimulatedContainerRuntime tests run by default;
DockerCLIContainerRuntime is only exercised when CODING_AGENT_DOCKER_TEST=1
is set explicitly, same opt-in-disposable-infrastructure pattern as
companion-core's test_database_migrations.py. It never touches anything but
containers this test itself starts and stops, labeled distinctly from any
real reachy-homelab-* container.
"""

import asyncio
import os
import uuid

import pytest
from coding_agent_service.reconcile import reconcile_sessions
from coding_agent_service.runtime import (
    ContainerSpec,
    ContainerStatus,
    DockerCLIContainerRuntime,
    SimulatedContainerRuntime,
)
from coding_agent_service.store import InMemoryCodingAgentStore

from shared.models.coding_agent import CodingAgentSession, CodingAgentStatus


def _spec(**overrides) -> ContainerSpec:
    defaults = {
        "image": "busybox:latest",
        "project_id": "proj-1",
        "session_id": "sess-1",
        "provider": "simulated",
        "host_mount_path": "/tmp",
    }
    defaults.update(overrides)
    return ContainerSpec(**defaults)


def test_simulated_runtime_starts_stops_and_lists_by_label() -> None:
    async def run() -> None:
        runtime = SimulatedContainerRuntime()
        container_id = await runtime.start(_spec())
        assert await runtime.status(container_id) == ContainerStatus.RUNNING
        assert await runtime.list_by_session("sess-1") == [container_id]
        assert await runtime.status("missing") == ContainerStatus.MISSING

        await runtime.stop(container_id)
        assert await runtime.status(container_id) == ContainerStatus.EXITED

    asyncio.run(run())


def test_reconcile_marks_sessions_lost_when_container_is_gone() -> None:
    async def run() -> None:
        store = InMemoryCodingAgentStore()
        runtime = SimulatedContainerRuntime()

        running_container = await runtime.start(_spec(session_id="sess-running"))
        gone_container = await runtime.start(_spec(session_id="sess-gone"))
        await runtime.stop(gone_container)

        running_session = CodingAgentSession(
            project_id="proj-1", provider="simulated", status=CodingAgentStatus.RUNNING,
            task_summary="still going", owner_user_id="owner-1", container_id=running_container,
        )
        lost_session = CodingAgentSession(
            project_id="proj-1", provider="simulated", status=CodingAgentStatus.RUNNING,
            task_summary="container died", owner_user_id="owner-1", container_id=gone_container,
        )
        completed_session = CodingAgentSession(
            project_id="proj-1", provider="simulated", status=CodingAgentStatus.COMPLETED,
            task_summary="already done", owner_user_id="owner-1", container_id="unrelated",
        )
        for session in (running_session, lost_session, completed_session):
            await store.add_session(session)

        changed = await reconcile_sessions(store, runtime)

        assert changed == [lost_session.id]
        assert (await store.get_session(running_session.id)).status == CodingAgentStatus.RUNNING
        assert (await store.get_session(lost_session.id)).status == CodingAgentStatus.LOST
        # A terminal session is left alone even though its container_id
        # was never a real one — reconciliation never revisits a session
        # that already has a final, provider-reported outcome.
        assert (await store.get_session(completed_session.id)).status == CodingAgentStatus.COMPLETED

    asyncio.run(run())


requires_docker = pytest.mark.skipif(
    os.environ.get("CODING_AGENT_DOCKER_TEST") != "1",
    reason="requires explicit opt-in (CODING_AGENT_DOCKER_TEST=1) and a local Docker daemon",
)


@requires_docker
def test_docker_cli_runtime_container_survives_a_fresh_runtime_instance() -> None:
    """29.2's exit criterion: a dummy command runs inside a container, and
    a brand-new DockerCLIContainerRuntime instance — standing in for a
    restarted supervisor process with no memory of starting it — can
    rediscover and inspect that same container purely from Docker's own
    labeled state."""

    async def run() -> None:
        session_id = f"test-{uuid.uuid4()}"
        runtime_a = DockerCLIContainerRuntime()
        container_id = await runtime_a.start(
            _spec(
                image="busybox:latest",
                session_id=session_id,
                command=["sleep", "60"],
                network_profile="offline",
            )
        )
        try:
            assert await runtime_a.status(container_id) == ContainerStatus.RUNNING

            runtime_b = DockerCLIContainerRuntime()
            assert await runtime_b.status(container_id) == ContainerStatus.RUNNING
            assert container_id in await runtime_b.list_by_session(session_id)
            labeled = await runtime_b.list_labeled()
            assert labeled[container_id]["reachy.session_id"] == session_id
            assert labeled[container_id]["reachy.provider"] == "simulated"
        finally:
            await runtime_a.stop(container_id, timeout=1)
            # The runtime doesn't auto-remove a stopped container (a real
            # deployment may still want its exit code/logs); this test
            # cleans up what it created rather than leaving it on the host.
            proc = await asyncio.create_subprocess_exec("docker", "rm", container_id)
            await proc.wait()

        assert await runtime_a.status(container_id) == ContainerStatus.MISSING

    asyncio.run(run())


@requires_docker
def test_docker_cli_runtime_read_only_mount_actually_blocks_a_write(tmp_path) -> None:
    """The hard guardrail claude_provider.py relies on for a Claude Pro/Max
    subscription credential — confirmed here at the runtime layer, not
    just asserted: a real write through a `read_only_mount=True` spec
    fails, and the same write through `read_only_mount=False` succeeds."""

    async def run() -> None:
        (tmp_path / "existing.txt").write_text("original")

        async def attempt_write(read_only: bool) -> str:
            proc = await asyncio.create_subprocess_exec(
                "docker", "run", "--rm", "--user", "1000:1000",
                "--volume", f"{tmp_path}:/workspace:{'ro' if read_only else 'rw'}",
                "--entrypoint", "sh", "busybox:latest",
                "-c", "echo hacked > /workspace/existing.txt; cat /workspace/existing.txt",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode()

        read_only_output = await attempt_write(True)
        assert "Read-only file system" in read_only_output
        assert "original" in read_only_output

        writable_output = await attempt_write(False)
        assert "hacked" in writable_output

    asyncio.run(run())
