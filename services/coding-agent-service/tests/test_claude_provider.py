"""29.3: ClaudeCodeProvider, exercised against SimulatedContainerRuntime
with log fixtures captured from a real container run (docker run
reachy-coding-agent-claude:latest --help / -p "..." --output-format
stream-json, claude-code 2.1.197, no real credential — see
claude_provider.py's module docstring). No real Docker or Anthropic API
call happens in this file.
"""

import asyncio
import json

import pytest
from coding_agent_service.claude_provider import ClaudeCodeProvider
from coding_agent_service.credentials import InMemoryCredentialStore
from coding_agent_service.providers import ProviderError
from coding_agent_service.runtime import ContainerStatus, SimulatedContainerRuntime
from coding_agent_service.store import InMemoryCodingAgentStore

from shared.models.coding_agent import (
    CodingAgentSession,
    CodingAgentStatus,
    CodingProject,
    CredentialKind,
)

INIT_LINE = {
    "type": "system", "subtype": "init", "cwd": "/workspace",
    "session_id": "07513f73-02a5-4cf8-9d06-06409c716d7e",
    "tools": ["Bash", "Read", "Write"], "model": "claude-opus-4-8[1m]",
    "permissionMode": "default", "apiKeySource": "ANTHROPIC_API_KEY",
    "claude_code_version": "2.1.197",
}

AUTH_RETRY_LINE = {
    "type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 10,
    "retry_delay_ms": 622.14, "error_status": 401, "error": "authentication_failed",
    "session_id": "07513f73-02a5-4cf8-9d06-06409c716d7e",
}

RATE_LIMIT_RETRY_LINE = {**AUTH_RETRY_LINE, "error_status": 429, "error": "rate_limited"}

SUCCESS_RESULT_LINE = {
    "type": "result", "subtype": "success", "is_error": False,
    "session_id": "07513f73-02a5-4cf8-9d06-06409c716d7e",
    "result": "Refactored module X and ran the tests; all green.",
    "usage": {"input_tokens": 1200, "output_tokens": 340},
    "total_cost_usd": 0.0421,
}

ERROR_RESULT_LINE = {
    "type": "result", "subtype": "error_max_turns", "is_error": True,
    "session_id": "07513f73-02a5-4cf8-9d06-06409c716d7e",
    "result": "Stopped after reaching the maximum number of turns.",
    "usage": {"input_tokens": 500, "output_tokens": 50},
    "total_cost_usd": 0.01,
}


def _jsonl(*lines) -> str:
    return "\n".join(json.dumps(line) for line in lines)


async def _setup(credential: str | None = "sk-ant-fixture-key"):
    store = InMemoryCodingAgentStore()
    runtime = SimulatedContainerRuntime()
    credentials = InMemoryCredentialStore()
    if credential:
        await credentials.set_credential("claude-code", CredentialKind.API_KEY, credential)
    provider = ClaudeCodeProvider(runtime, credentials, store)
    project = await store.add_project(
        CodingProject(name="Reachy Work Buddy", repository_path="/projects/reachy-work-buddy", provider="claude-code")
    )
    return store, runtime, credentials, provider, project


def test_start_session_assigns_a_session_id_without_waiting_for_output() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="Refactor module X",
            owner_user_id="owner-1",
        )
        event = await provider.start_session(session)

        assert event.status == CodingAgentStatus.RUNNING
        assert event.provider_session_id  # a UUID was assigned up front
        container_id = event.metadata["container_id"]
        assert await runtime.status(container_id) == ContainerStatus.RUNNING

    asyncio.run(run())


def test_start_session_sends_an_api_key_credential_as_anthropic_api_key() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup(credential="sk-ant-fixture-key")
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="x", owner_user_id="owner-1",
        )
        event = await provider.start_session(session)
        spec = runtime.specs[event.metadata["container_id"]]
        assert spec.env == {"ANTHROPIC_API_KEY": "sk-ant-fixture-key"}

    asyncio.run(run())


def test_start_session_sends_an_oauth_token_credential_as_claude_code_oauth_token() -> None:
    async def run() -> None:
        store = InMemoryCodingAgentStore()
        runtime = SimulatedContainerRuntime()
        credentials = InMemoryCredentialStore()
        # A Claude Pro/Max subscription's long-lived token (from `claude
        # setup-token`, run interactively elsewhere) must go in a
        # different env var than a pay-per-use API key — confirmed live by
        # grepping the real claude.exe binary (claude_provider.py's module
        # docstring); using the wrong one would silently fail to auth.
        await credentials.set_credential("claude-code", CredentialKind.OAUTH_TOKEN, "sk-ant-oat01-fixture")
        provider = ClaudeCodeProvider(runtime, credentials, store)
        project = await store.add_project(
            CodingProject(name="X", repository_path="/x", provider="claude-code")
        )
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="x", owner_user_id="owner-1",
        )

        event = await provider.start_session(session)
        spec = runtime.specs[event.metadata["container_id"]]
        assert spec.env == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture"}

    asyncio.run(run())


def test_start_session_without_a_credential_raises_provider_error() -> None:
    async def run() -> None:
        _, _, _, provider, project = await _setup(credential=None)
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="x", owner_user_id="owner-1",
        )
        with pytest.raises(ProviderError):
            await provider.start_session(session)

    asyncio.run(run())


def test_inspect_session_reports_running_while_container_is_active_with_no_result_yet() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="Refactor module X", owner_user_id="owner-1",
        )
        event = await provider.start_session(session)
        session.container_id = event.metadata["container_id"]
        session.provider_session_id = event.provider_session_id
        runtime.set_logs(session.container_id, _jsonl(INIT_LINE))

        inspected = await provider.inspect_session(session)
        assert inspected.status == CodingAgentStatus.RUNNING

    asyncio.run(run())


def test_inspect_session_reports_completed_with_usage_from_the_final_result() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="Refactor module X", owner_user_id="owner-1",
        )
        event = await provider.start_session(session)
        session.container_id = event.metadata["container_id"]
        session.provider_session_id = event.provider_session_id
        runtime.set_logs(session.container_id, _jsonl(INIT_LINE, SUCCESS_RESULT_LINE))
        await runtime.stop(session.container_id)

        inspected = await provider.inspect_session(session)
        assert inspected.status == CodingAgentStatus.COMPLETED
        assert "Refactored module X" in inspected.summary

        usage = await provider.collect_usage(session)
        values = {d.name: d.value for d in usage.dimensions}
        assert values["input_tokens"] == 1200
        assert values["output_tokens"] == 340
        assert values["session_cost"] == pytest.approx(0.0421)

    asyncio.run(run())


def test_inspect_session_reports_failed_on_an_error_result() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="Refactor module X", owner_user_id="owner-1",
        )
        event = await provider.start_session(session)
        session.container_id = event.metadata["container_id"]
        runtime.set_logs(session.container_id, _jsonl(INIT_LINE, ERROR_RESULT_LINE))
        await runtime.stop(session.container_id)

        inspected = await provider.inspect_session(session)
        assert inspected.status == CodingAgentStatus.FAILED
        assert "maximum number of turns" in inspected.summary

    asyncio.run(run())


def test_inspect_session_reports_lost_when_container_disappears_without_a_result() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="Refactor module X", owner_user_id="owner-1",
        )
        event = await provider.start_session(session)
        session.container_id = event.metadata["container_id"]
        runtime.set_logs(session.container_id, _jsonl(INIT_LINE))
        await runtime.stop(session.container_id)

        inspected = await provider.inspect_session(session)
        assert inspected.status == CodingAgentStatus.LOST

    asyncio.run(run())


def test_inspect_session_detects_rate_limiting_while_still_running() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="Refactor module X", owner_user_id="owner-1",
        )
        event = await provider.start_session(session)
        session.container_id = event.metadata["container_id"]
        runtime.set_logs(session.container_id, _jsonl(INIT_LINE, RATE_LIMIT_RETRY_LINE))

        inspected = await provider.inspect_session(session)
        assert inspected.status == CodingAgentStatus.RATE_LIMITED

    asyncio.run(run())


def test_resume_session_requires_an_existing_provider_session_id() -> None:
    async def run() -> None:
        _, _, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="x", owner_user_id="owner-1",
        )
        with pytest.raises(ProviderError):
            await provider.resume_session(session, "keep going")

    asyncio.run(run())


def test_resume_session_starts_a_new_container_reusing_the_same_provider_session_id() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="ask: which approach?",
            owner_user_id="owner-1", provider_session_id="existing-session-id",
        )
        event = await provider.resume_session(session, "Use approach B.")
        assert event.status == CodingAgentStatus.RUNNING
        assert event.provider_session_id == "existing-session-id"
        assert await runtime.status(event.metadata["container_id"]) == ContainerStatus.RUNNING

    asyncio.run(run())


def test_stop_session_stops_the_container() -> None:
    async def run() -> None:
        _, runtime, _, provider, project = await _setup()
        session = CodingAgentSession(
            project_id=project.id, provider="claude-code", task_summary="Refactor module X", owner_user_id="owner-1",
        )
        event = await provider.start_session(session)
        session.container_id = event.metadata["container_id"]

        stop_event = await provider.stop_session(session)
        assert stop_event.status == CodingAgentStatus.STOPPED
        assert await runtime.status(session.container_id) == ContainerStatus.EXITED

    asyncio.run(run())


def test_capabilities_reflect_what_this_adapter_can_actually_report() -> None:
    _, _, _, provider, _ = asyncio.run(_setup())
    caps = provider.capabilities()
    assert caps.provider == "claude-code"
    assert caps.resumable_sessions is True
    assert caps.completion_events is True
    assert caps.token_usage is True
    assert caps.monetary_cost is True
    # 29.4 (hooks) hasn't landed yet — this adapter cannot see a mid-task
    # permission/input wait, only a task's final result.
    assert caps.needs_input_events is False
    assert caps.permission_events is False
