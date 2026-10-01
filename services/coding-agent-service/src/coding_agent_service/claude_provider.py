"""29.3: the real Claude Code CLI adapter, running `claude` inside the
image built from docker/claude-code/Dockerfile. Confirmed live against
claude-code 2.1.197 (`docker run reachy-coding-agent-claude:latest
--help`/`-p "..." --output-format stream-json`, no real credential needed
for that shape check): `-p`/`--output-format stream-json` prints one JSON
object per line — a `{"type":"system","subtype":"init",...,"session_id":
"..."}` line first, then zero or more progress lines, then a final
`{"type":"result",...}` line. This adapter does not rely on parsing the
init line for the session id, though: `--session-id <uuid>` lets it assign
one itself up front, so start_session knows the provider_session_id
immediately rather than waiting on container output.

This module never passes --dangerously-skip-permissions or
--allow-dangerously-skip-permissions — AGENTS.md's stance that "the LLM
has no authority to bypass an action gate" applies to this CLI's own tool
permissions exactly as much as to Reachy's. A tool call that would need
approval under --permission-mode default simply has nothing to approve it
headlessly; 29.4 (hook-based permission-request detection) is what
eventually surfaces that to the owner instead of it just failing silently
in the transcript.
"""

from __future__ import annotations

import json
import uuid

from coding_agent_service.credentials import CredentialStore
from coding_agent_service.providers import ProviderError, ProviderEvent
from coding_agent_service.runtime import (
    ContainerRuntime,
    ContainerSpec,
    ContainerStatus,
)
from coding_agent_service.store import CodingAgentStore
from shared.models.coding_agent import (
    CodingAgentSession,
    CodingAgentStatus,
    ProviderCapabilities,
    UsageDimension,
    UsageSnapshot,
)

DEFAULT_IMAGE = "reachy-coding-agent-claude:latest"

# 29.8: a task that hits this limit without a final result event is
# reported LOST, never COMPLETED — silence from the container is not
# completion evidence.
_PRINT_FLAGS = ["--output-format", "stream-json", "--verbose", "--permission-mode", "default"]


def _parse_stream_json(logs: str) -> list[dict]:
    events = []
    for line in logs.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _extract_result(events: list[dict]) -> dict | None:
    for event in reversed(events):
        if event.get("type") == "result":
            return event
    return None


def _latest_retry_error_status(events: list[dict]) -> int | None:
    """Opportunistic 29.12 signal: confirmed live that an auth failure
    produces repeated {"type":"system","subtype":"api_retry",
    "error_status":401,...} lines while the CLI keeps retrying — the same
    shape a 429 rate-limit would produce mid-task. This is a heuristic,
    not 29.12's full rate-limit handling (no reset_at here)."""
    status = None
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "api_retry":
            status = event.get("error_status")
    return status


def _usage_dimensions(result: dict) -> list[UsageDimension]:
    dimensions = []
    usage = result.get("usage") or {}
    for key, name in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens")):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            dimensions.append(UsageDimension(name=name, value=float(value), unit="tokens"))
    cost = result.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        dimensions.append(UsageDimension(name="session_cost", value=float(cost), unit="usd"))
    return dimensions


class ClaudeCodeProvider:
    """CodingAgentProvider implementation. `credentials` and `projects` are
    the narrow interfaces this adapter needs — a CredentialStore to find
    the owner-entered API key (29.19) and a CodingAgentStore to resolve a
    project's repository_path (29.4's registry; never a free-form path
    from the session request itself)."""

    def __init__(
        self,
        runtime: ContainerRuntime,
        credentials: CredentialStore,
        projects: CodingAgentStore,
        *,
        image: str = DEFAULT_IMAGE,
    ) -> None:
        self._runtime = runtime
        self._credentials = credentials
        self._projects = projects
        self._image = image

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider="claude-code",
            resumable_sessions=True,
            completion_events=True,
            # 29.4 (hooks) is what turns a mid-task permission/input wait
            # into its own normalized event; this adapter only sees a
            # task's final result, so it cannot report these yet.
            needs_input_events=False,
            permission_events=False,
            usage_percentages=False,
            token_usage=True,
            monetary_cost=True,
            context_usage=False,
            structured_stream=True,
        )

    async def _credential(self) -> str:
        secret = await self._credentials.get_secret("claude-code")
        if not secret:
            raise ProviderError(
                "No claude-code credential configured; set one in the operator UI's "
                "Settings · Accounts · Coding agent credentials card first"
            )
        return secret

    async def _spec(self, session: CodingAgentSession, command: list[str]) -> ContainerSpec:
        project = await self._projects.get_project(session.project_id)
        if project is None:
            raise ProviderError(f"Unknown project {session.project_id}")
        secret = await self._credential()
        return ContainerSpec(
            image=self._image,
            project_id=session.project_id,
            session_id=session.id,
            provider="claude-code",
            host_mount_path=project.repository_path,
            command=command,
            env={"ANTHROPIC_API_KEY": secret},
            network_profile=project.allowed_network_profile,
        )

    async def start_session(self, session: CodingAgentSession) -> ProviderEvent:
        provider_session_id = str(uuid.uuid4())
        command = ["-p", session.task_summary, "--session-id", provider_session_id, *_PRINT_FLAGS]
        spec = await self._spec(session, command)
        container_id = await self._runtime.start(spec)
        return ProviderEvent(
            status=CodingAgentStatus.RUNNING,
            summary="Claude Code started",
            provider_session_id=provider_session_id,
            metadata={"container_id": container_id},
        )

    async def resume_session(self, session: CodingAgentSession, instruction: str) -> ProviderEvent:
        if not session.provider_session_id:
            raise ProviderError("No provider session id to resume")
        command = ["-p", instruction, "--resume", session.provider_session_id, *_PRINT_FLAGS]
        spec = await self._spec(session, command)
        container_id = await self._runtime.start(spec)
        return ProviderEvent(
            status=CodingAgentStatus.RUNNING,
            summary=f"Claude Code resumed with owner instruction: {instruction!r}",
            provider_session_id=session.provider_session_id,
            metadata={"container_id": container_id},
        )

    async def send_input(self, session: CodingAgentSession, text: str) -> ProviderEvent:
        return await self.resume_session(session, text)

    async def stop_session(self, session: CodingAgentSession) -> ProviderEvent:
        if session.container_id:
            await self._runtime.stop(session.container_id)
        return ProviderEvent(
            status=CodingAgentStatus.STOPPED,
            summary="Claude Code session stopped by owner request",
            provider_session_id=session.provider_session_id,
        )

    async def inspect_session(self, session: CodingAgentSession) -> ProviderEvent:
        if not session.container_id:
            raise ProviderError("No container associated with this session")
        container_status = await self._runtime.status(session.container_id)
        events = _parse_stream_json(await self._runtime.logs(session.container_id))
        result = _extract_result(events)

        if result is None:
            if container_status == ContainerStatus.RUNNING:
                retry_status = _latest_retry_error_status(events)
                if retry_status == 429:
                    return ProviderEvent(
                        status=CodingAgentStatus.RATE_LIMITED,
                        summary="Claude Code is being rate-limited by the API and retrying",
                        provider_session_id=session.provider_session_id,
                        metadata={"container_id": session.container_id},
                    )
                return ProviderEvent(
                    status=CodingAgentStatus.RUNNING,
                    summary="Claude Code is still working",
                    provider_session_id=session.provider_session_id,
                    metadata={"container_id": session.container_id},
                )
            # 29.8: the container is gone with no final result line — this
            # is not evidence of success, so it is never reported COMPLETED.
            return ProviderEvent(
                status=CodingAgentStatus.LOST,
                summary="Claude Code's container stopped without producing a final result",
                provider_session_id=session.provider_session_id,
                metadata={"container_id": session.container_id},
            )

        metadata = {"container_id": session.container_id, "usage": result.get("usage"), "total_cost_usd": result.get("total_cost_usd")}
        if result.get("is_error"):
            return ProviderEvent(
                status=CodingAgentStatus.FAILED,
                summary=(result.get("result") or "Claude Code reported an error")[:2000],
                provider_session_id=session.provider_session_id,
                metadata=metadata,
            )
        return ProviderEvent(
            status=CodingAgentStatus.COMPLETED,
            summary=(result.get("result") or "Claude Code finished")[:2000],
            provider_session_id=session.provider_session_id,
            metadata=metadata,
        )

    async def collect_usage(self, session: CodingAgentSession) -> UsageSnapshot:
        dimensions: list[UsageDimension] = []
        if session.container_id:
            events = _parse_stream_json(await self._runtime.logs(session.container_id))
            result = _extract_result(events)
            if result is not None:
                dimensions = _usage_dimensions(result)
        return UsageSnapshot(session_id=session.id, provider="claude-code", dimensions=dimensions)
