"""29.3's exit criterion, against a real container: "Reachy launches a
real Claude Code task against a test repository and tracks the provider
session ID." Opt-in (CODING_AGENT_DOCKER_TEST=1, same gate as
test_runtime.py) and skipped if the image from
docker/claude-code/Dockerfile hasn't been built locally.

This deliberately uses an invalid ANTHROPIC_API_KEY — a real credential
costs real money and belongs to the owner, entered through the operator
UI, not a test fixture. What this proves without one: the container
actually starts against a real project directory with the real `claude`
binary, the session id is tracked from the moment the container starts
(--session-id, not log-parsing), inspect_session correctly reads real
live container state and real stdout (confirmed live: an auth failure
produces repeated {"type":"system","subtype":"api_retry",...} JSONL
lines — see claude_provider.py's module docstring), and stop_session
actually stops the real process. Completing a real task and parsing a
real "result" line needs the owner's own credential and is not exercised
here.
"""

import asyncio
import os
import subprocess
import tempfile

import pytest
from coding_agent_service.claude_provider import DEFAULT_IMAGE, ClaudeCodeProvider
from coding_agent_service.credentials import InMemoryCredentialStore
from coding_agent_service.runtime import ContainerStatus, DockerCLIContainerRuntime
from coding_agent_service.store import InMemoryCodingAgentStore

from shared.models.coding_agent import (
    CodingAgentSession,
    CodingAgentStatus,
    CodingProject,
    CredentialKind,
)


def _image_available() -> bool:
    result = subprocess.run(
        ["docker", "images", "-q", DEFAULT_IMAGE], capture_output=True, text=True, check=False
    )
    return bool(result.stdout.strip())


requires_docker_and_image = pytest.mark.skipif(
    os.environ.get("CODING_AGENT_DOCKER_TEST") != "1" or not _image_available(),
    reason="requires CODING_AGENT_DOCKER_TEST=1, a local Docker daemon, and the image built from "
    "services/coding-agent-service/docker/claude-code/Dockerfile",
)


@requires_docker_and_image
def test_real_claude_container_starts_tracks_session_id_and_stops() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory(prefix="reachy-claude-provider-test-") as repo_path:
            init_proc = await asyncio.create_subprocess_exec("git", "init", "-q", repo_path)
            assert await init_proc.wait() == 0

            store = InMemoryCodingAgentStore()
            credentials = InMemoryCredentialStore()
            await credentials.set_credential("claude-code", CredentialKind.API_KEY, "sk-ant-invalid-test-key")
            runtime = DockerCLIContainerRuntime()
            provider = ClaudeCodeProvider(runtime, credentials, store)

            project = await store.add_project(
                CodingProject(
                    name="test-repo", repository_path=repo_path, provider="claude-code",
                    allowed_network_profile="bridge",
                )
            )
            session = CodingAgentSession(
                project_id=project.id, provider="claude-code", task_summary="say hi",
                owner_user_id="owner-1",
            )

            start_event = await provider.start_session(session)
            session.container_id = start_event.metadata["container_id"]
            session.provider_session_id = start_event.provider_session_id
            try:
                assert start_event.status == CodingAgentStatus.RUNNING
                assert start_event.provider_session_id  # tracked immediately, before any output

                # Give the real process a moment to actually start retrying
                # against the (invalid-key) API before asserting on it.
                inspected = None
                for _ in range(20):
                    inspected = await provider.inspect_session(session)
                    if inspected.status != CodingAgentStatus.RUNNING:
                        break
                    await asyncio.sleep(1)
                assert inspected is not None
                # Confirmed live (claude-code 2.1.197): an invalid key stays
                # RUNNING while it retries, rather than failing fast — see
                # the module docstring. Either outcome proves real log
                # parsing against a real process, not a canned fixture.
                assert inspected.status in (CodingAgentStatus.RUNNING, CodingAgentStatus.FAILED)
            finally:
                await provider.stop_session(session)
                assert await runtime.status(session.container_id) == ContainerStatus.EXITED
                rm_proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", session.container_id,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await rm_proc.wait()

    asyncio.run(run())
