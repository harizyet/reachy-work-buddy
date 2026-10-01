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

Confirmed live by grepping the installed claude.exe binary for its env-var
names: a Claude Pro/Max subscription is supported, not just pay-per-use API
billing, via a long-lived token (`claude setup-token`, run interactively
on a machine where the owner can log in — this container cannot do that
itself) read from CLAUDE_CODE_OAUTH_TOKEN, distinct from ANTHROPIC_API_KEY.
_credential_env picks the right variable from the stored CredentialKind.

This module never passes --dangerously-skip-permissions or
--allow-dangerously-skip-permissions — AGENTS.md's stance that "the LLM
has no authority to bypass an action gate" applies to this CLI's own tool
permissions exactly as much as to Reachy's. A tool call that would need
approval under --permission-mode default simply has nothing to approve it
headlessly; 29.4 (hook-based permission-request detection) is what
eventually surfaces that to the owner instead of it just failing silently
in the transcript.

**No-invocation guardrail for a real Claude Pro/Max subscription — added
2026-10-01, lifted the same day (owner request):** this integration had
never completed a real task against the real Anthropic API, so
`start_session`/`resume_session`/`send_input` initially refused outright
for a CLAUDE_CODE_OAUTH_TOKEN credential, before any container, Docker
call or project lookup happened. Once the owner had actually registered a
subscription credential through the operator UI and asked to test it for
real, that block was removed from `_ensure_can_invoke` — it now only
refuses when no credential is configured at all, for either kind. The
read-only layers below (previously dormant for a subscription credential,
since the block stopped execution before `_build` ran) are now the live
protection for a real subscription session, not a theoretical one for
later. Lifting the block was a deliberate code change with its own dated
reasoning, same as the guardrail it replaced — not a quiet revert.

`_build` still restricts a subscription-credentialed session to read-only
— it can now actually run, but not write files or execute shell commands —
while an API-key session keeps full default permissions. That split is
deliberate, not a leftover: a brand-new, never-yet-proven subscription
path gets to prove itself read-only first. Verified live, not assumed:

1. A Docker-enforced read-only bind mount (`ContainerSpec.read_only_mount`
   -> `docker run -v host:/workspace:ro`) — confirmed by actually trying to
   write a file through exactly this mount and getting "Read-only file
   system", including via `docker exec` into a live `claude` process. This
   is the one layer that holds regardless of anything the process does,
   including a shell, and does not depend on trusting the CLI's own tool
   policy at all.
2. `--disallowedTools` naming every tool except a small read-only set
   (Read, Grep, Glob, WebSearch, WebFetch) — confirmed live that this is
   the flag that actually removes tools from the session's active set
   (they disappear from the init event's `"tools"` array). **`--allowedTools`
   was tested live alongside it and did *not* restrict anything by
   itself** — tools absent from that list but also not explicitly
   disallowed (Task, the Cron*/Schedule* family, SendMessage, DesignSync,
   Workflow, Skill, ReportFindings, TaskCreate/Update/Stop, ...) stayed
   available. It is still passed, but only as an unverified secondary
   signal, never as the thing actually doing the restricting — read
   `_READ_ONLY_DISALLOWED_TOOLS`'s own comment before trusting an allowlist
   here. A tool name Anthropic adds later that this list doesn't know
   about is a gap in this layer specifically, which is exactly why layer 1
   above exists and does not have that problem.
3. `--permission-mode plan`, the product's own no-execution research mode
   — a behavioral instruction to the model, not independently confirmed to
   remove tools from the active set on its own in this test.
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
    CredentialKind,
    ProviderCapabilities,
    UsageDimension,
    UsageSnapshot,
)

DEFAULT_IMAGE = "reachy-coding-agent-claude:latest"

# Hard read-only guardrail (see module docstring point 2 for how this was
# actually tested, not assumed). _READ_ONLY_DISALLOWED_TOOLS is every tool
# name claude-code 2.1.197 has been observed to advertise in a live init
# event, minus the small set below — confirmed to work by diffing a real
# container's "tools" array with and without --disallowedTools set.
# --allowedTools is passed too but is NOT what does the restricting (see
# the docstring); treat this module's actual guarantee as layer 1 (the
# read-only mount), with this list as best-effort hardening that a new
# tool name Anthropic ships later could fall outside of.
_READ_ONLY_ALLOWED_TOOLS = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]
_READ_ONLY_DISALLOWED_TOOLS = [
    "Task", "Bash", "CronCreate", "CronDelete", "CronList", "DesignSync", "Edit",
    "EnterWorktree", "ExitWorktree", "Monitor", "NotebookEdit", "PushNotification",
    "ReportFindings", "ScheduleWakeup", "SendMessage", "Skill", "TaskCreate", "TaskGet",
    "TaskList", "TaskOutput", "TaskStop", "TaskUpdate", "ToolSearch", "Workflow", "Write",
]


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

    async def _credential(self) -> tuple[CredentialKind, str]:
        """Claude Code reads two different env vars depending on how the
        owner authenticates (confirmed live by grepping the real
        claude.exe binary for its env-var names, not guessed): a
        pay-per-use API key is ANTHROPIC_API_KEY, but a Claude Pro/Max
        subscription's long-lived token (generated interactively with
        `claude setup-token` — not something this headless container can
        do itself) is CLAUDE_CODE_OAUTH_TOKEN. Using the wrong variable
        for the stored CredentialKind would silently try to bill the
        subscription token as an API key and fail authentication. The
        returned kind also drives the read-only guardrail below."""
        record = await self._credentials.describe("claude-code")
        secret = await self._credentials.get_secret("claude-code")
        if not record or not secret:
            raise ProviderError(
                "No claude-code credential configured; set one in the operator UI's "
                "Settings · Accounts · Coding agent credentials card first"
            )
        return record.kind, secret

    async def _ensure_can_invoke(self) -> None:
        """29.3: refuses only when no credential is configured at all.
        The OAuth-token invocation block that lived here (owner request,
        2026-10-01) was deliberately lifted the same day, once the owner
        had actually registered a subscription credential and asked to
        test it for real — see the module docstring's "Lifting the
        no-invocation guardrail" note for exactly what still protects a
        subscription session (the read-only layers in `_build`, now live
        rather than dormant) and what doesn't (there is still no hook-based
        permission/input detection, 29.4)."""
        record = await self._credentials.describe("claude-code")
        if record is None:
            raise ProviderError(
                "No claude-code credential configured; set one in the operator UI's "
                "Settings · Accounts · Coding agent credentials card first"
            )

    async def _build(self, session: CodingAgentSession, *, prompt: str, resume: bool) -> tuple[ContainerSpec, str]:
        project = await self._projects.get_project(session.project_id)
        if project is None:
            raise ProviderError(f"Unknown project {session.project_id}")
        kind, secret = await self._credential()
        env_var = "ANTHROPIC_API_KEY" if kind == CredentialKind.API_KEY else "CLAUDE_CODE_OAUTH_TOKEN"

        provider_session_id = session.provider_session_id if resume else str(uuid.uuid4())
        command = ["-p", prompt, "--output-format", "stream-json", "--verbose"]
        command += ["--resume", provider_session_id] if resume else ["--session-id", provider_session_id]

        read_only = kind == CredentialKind.OAUTH_TOKEN
        if read_only:
            # Hard guardrail — see module docstring. Three independent
            # layers: plan mode, an explicit tool allow/deny pair, and
            # (below) a Docker-enforced read-only mount.
            command += [
                "--permission-mode", "plan",
                "--allowedTools", *_READ_ONLY_ALLOWED_TOOLS,
                "--disallowedTools", *_READ_ONLY_DISALLOWED_TOOLS,
            ]
        else:
            command += ["--permission-mode", "default"]

        spec = ContainerSpec(
            image=self._image,
            project_id=session.project_id,
            session_id=session.id,
            provider="claude-code",
            host_mount_path=project.repository_path,
            command=command,
            env={env_var: secret},
            network_profile=project.allowed_network_profile,
            read_only_mount=read_only,
        )
        return spec, provider_session_id

    async def start_session(self, session: CodingAgentSession) -> ProviderEvent:
        await self._ensure_can_invoke()
        spec, provider_session_id = await self._build(session, prompt=session.task_summary, resume=False)
        container_id = await self._runtime.start(spec)
        read_only_note = " (read-only: a Claude Pro/Max subscription credential cannot write yet)" if spec.read_only_mount else ""
        return ProviderEvent(
            status=CodingAgentStatus.RUNNING,
            summary=f"Claude Code started{read_only_note}",
            provider_session_id=provider_session_id,
            metadata={"container_id": container_id},
        )

    async def resume_session(self, session: CodingAgentSession, instruction: str) -> ProviderEvent:
        if not session.provider_session_id:
            raise ProviderError("No provider session id to resume")
        await self._ensure_can_invoke()
        spec, provider_session_id = await self._build(session, prompt=instruction, resume=True)
        container_id = await self._runtime.start(spec)
        read_only_note = " (read-only: a Claude Pro/Max subscription credential cannot write yet)" if spec.read_only_mount else ""
        return ProviderEvent(
            status=CodingAgentStatus.RUNNING,
            summary=f"Claude Code resumed with owner instruction{read_only_note}: {instruction!r}",
            provider_session_id=provider_session_id,
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
