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

import asyncio
import json
import logging
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

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
    InterventionState,
    ProviderCapabilities,
    UsageDimension,
    UsageSnapshot,
)

logger = logging.getLogger(__name__)

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
    "Task",
    "Bash",
    "CronCreate",
    "CronDelete",
    "CronList",
    "DesignSync",
    "Edit",
    "EnterWorktree",
    "ExitWorktree",
    "Monitor",
    "NotebookEdit",
    "PushNotification",
    "ReportFindings",
    "ScheduleWakeup",
    "SendMessage",
    "Skill",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "TaskUpdate",
    "ToolSearch",
    "Workflow",
    "Write",
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


_QUESTION_TOOL = "AskUserQuestion"


def _tool_uses(events: list[dict]) -> list[dict]:
    uses = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        content = (event.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        uses += [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
    return uses


def _question_text(tool_use: dict) -> str | None:
    """Text of the agent's own ask-the-owner tool call, if it has any."""
    questions = (tool_use.get("input") or {}).get("questions")
    if isinstance(questions, str):
        # Observed live: the CLI delivers the list JSON-encoded as a string.
        try:
            questions = json.loads(questions)
        except json.JSONDecodeError:
            return questions[:2000] or None
    if not isinstance(questions, list):
        return None
    texts = [q.get("question") for q in questions if isinstance(q, dict) and q.get("question")]
    return "\n".join(texts)[:2000] or None


def _classify_intervention(
    events: list[dict], result: dict
) -> tuple[CodingAgentStatus, InterventionState, str | None, str | None]:
    """Only signals observed in live characterization (docs/phase-29.md):
    a headless run that needs the owner still ends `subtype: success`, so
    the result line alone says nothing. A `permission_denials` entry or the
    agent's AskUserQuestion tool call are explicit (confirmed); a final
    message ending in a question mark is only a heuristic (suspected)."""
    denials = result.get("permission_denials")
    if isinstance(denials, list) and denials:
        names = sorted({str(d.get("tool_name")) for d in denials if isinstance(d, dict)})
        return (
            CodingAgentStatus.WAITING_FOR_PERMISSION,
            InterventionState.CONFIRMED,
            "result.permission_denials",
            f"Permission needed for: {', '.join(names)}",
        )
    for use in reversed(_tool_uses(events)):
        if use.get("name") == _QUESTION_TOOL:
            return (
                CodingAgentStatus.WAITING_FOR_INPUT,
                InterventionState.CONFIRMED,
                f"tool_use.{_QUESTION_TOOL}",
                _question_text(use),
            )
    text = (result.get("result") or "").rstrip()
    if text.endswith("?"):
        return (
            CodingAgentStatus.COMPLETED,
            InterventionState.SUSPECTED,
            "final_message_question",
            text[-500:],
        )
    return CodingAgentStatus.COMPLETED, InterventionState.NONE, None, None


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


# 29.26: claude-code 2.1.197 emits {"type":"rate_limit_event",
# "rate_limit_info":{"status","resetsAt","rateLimitType","utilization",...}}
# when its account rate-limit state changes. Field names, the epoch-seconds
# resetsAt and the 0..1 utilization fraction were read from the installed
# binary; no live event has been captured yet. `utilization` is only
# present once usage nears a threshold ("allowed_warning"), so a plain
# "allowed" event yields no percentage and must not be reported as 0%.
_ALLOWANCE_WINDOW_BY_RATE_LIMIT_TYPE = {
    "five_hour": "five_hour_window",
    "seven_day": "weekly_window",
    "seven_day_opus": "weekly_opus_window",
    "seven_day_sonnet": "weekly_sonnet_window",
}


def _allowance_dimensions(events: list[dict]) -> list[UsageDimension]:
    latest: dict[str, UsageDimension] = {}
    for event in events:
        if event.get("type") != "rate_limit_event":
            continue
        info = event.get("rate_limit_info")
        if not isinstance(info, dict):
            continue
        name = _ALLOWANCE_WINDOW_BY_RATE_LIMIT_TYPE.get(info.get("rateLimitType"))
        utilization = info.get("utilization")
        resets_at = info.get("resetsAt")
        if (
            name is None
            or isinstance(utilization, bool)
            or not isinstance(utilization, (int, float))
            or isinstance(resets_at, bool)
            or not isinstance(resets_at, (int, float))
        ):
            continue
        try:
            reset = datetime.fromtimestamp(resets_at, UTC)
        except (OverflowError, OSError, ValueError):
            continue
        latest[name] = UsageDimension(
            name=name, value=round(utilization * 100, 1), unit="%", resets_at=reset
        )
    return list(latest.values())


# The same endpoints Claude Code's own /usage screen and token refresh use
# (URLs and client id read from the pinned CLI binary). Undocumented, so
# every failure is surfaced as ProviderError and callers fall back to the
# last CLI-reported figures rather than guessing.
_OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
# The owner-pasted full-login credential, kept apart from the session
# credential: a `claude setup-token` token is inference-only and the usage
# endpoint refuses it (HTTP 403).
ACCOUNT_CREDENTIAL = "claude-code-account"
_REFRESH_MARGIN = timedelta(minutes=5)
_LIVE_WINDOW_KEYS = {
    "five_hour": "five_hour_window",
    "seven_day": "weekly_window",
    "seven_day_opus": "weekly_opus_window",
    "seven_day_sonnet": "weekly_sonnet_window",
}


def _http_json(request: urllib.request.Request, what: str) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # Never include the response body or request: keep tokens out of logs.
        raise ProviderError(
            f"Claude {what} refused the request (HTTP {exc.code})"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ProviderError(
            f"Claude {what} could not be reached or returned unreadable data"
        ) from None
    if not isinstance(body, dict):
        raise ProviderError(f"Claude {what} returned an unexpected shape")
    return body


def _fetch_oauth_usage(token: str) -> dict:
    return _http_json(
        urllib.request.Request(
            _OAUTH_USAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "reachy-coding-agent",
            },
        ),
        "usage endpoint",
    )


def _refresh_oauth_token(refresh_token: str) -> dict:
    return _http_json(
        urllib.request.Request(
            _OAUTH_TOKEN_URL,
            data=json.dumps(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": _OAUTH_CLIENT_ID,
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "reachy-coding-agent",
            },
            method="POST",
        ),
        "token refresh",
    )


def _parse_account_credential(raw: str) -> dict:
    """Accepts the whole ~/.claude/.credentials.json or just its
    `claudeAiOauth` object."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise ProviderError(
            "The stored Claude account credential is not valid JSON"
        ) from None
    if isinstance(data, dict) and isinstance(data.get("claudeAiOauth"), dict):
        data = data["claudeAiOauth"]
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("accessToken"), str)
        or not isinstance(data.get("refreshToken"), str)
    ):
        raise ProviderError(
            "The stored Claude account credential has no accessToken/refreshToken"
        )
    return data


def _live_allowance_dimensions(body: dict) -> list[UsageDimension]:
    """A null/absent window is simply not reported; utilization is 0..100."""
    dimensions = []
    for key, name in _LIVE_WINDOW_KEYS.items():
        window = body.get(key)
        if not isinstance(window, dict):
            continue
        utilization = window.get("utilization")
        resets_at = window.get("resets_at")
        if (
            isinstance(utilization, bool)
            or not isinstance(utilization, (int, float))
            or not isinstance(resets_at, str)
        ):
            continue
        try:
            reset = datetime.fromisoformat(resets_at)
        except ValueError:
            continue
        if reset.tzinfo is None:
            reset = reset.replace(tzinfo=UTC)
        dimensions.append(
            UsageDimension(
                name=name, value=round(float(utilization), 1), unit="%", resets_at=reset
            )
        )
    return dimensions


def _usage_dimensions(result: dict) -> list[UsageDimension]:
    dimensions = []
    usage = result.get("usage") or {}
    for key, name in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
    ):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            dimensions.append(
                UsageDimension(name=name, value=float(value), unit="tokens")
            )
    cost = result.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        dimensions.append(
            UsageDimension(name="session_cost", value=float(cost), unit="usd")
        )
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
        usage_fetch: Callable[[str], dict] = _fetch_oauth_usage,
        token_refresh: Callable[[str], dict] = _refresh_oauth_token,
    ) -> None:
        self._token_refresh = token_refresh
        self._account_lock = asyncio.Lock()
        self._usage_fetch = usage_fetch
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
            needs_input_events=True,
            permission_events=True,
            # Allowance percentages exist only when the CLI reports them,
            # i.e. once a limit window nears a warning threshold.
            usage_percentages=True,
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

    async def _account_access_token(self, *, force_refresh: bool = False) -> str | None:
        """The owner-pasted full-login token, refreshed when near expiry.
        The refresh token rotates, so the new pair is persisted before the
        new access token is used, under a lock so two readers never spend
        the same refresh token."""
        async with self._account_lock:
            raw = await self._credentials.get_secret(ACCOUNT_CREDENTIAL)
            if not raw:
                return None
            data = _parse_account_credential(raw)
            expires_ms = data.get("expiresAt")
            expired = (
                not isinstance(expires_ms, (int, float))
                or datetime.fromtimestamp(expires_ms / 1000, UTC) - datetime.now(UTC)
                < _REFRESH_MARGIN
            )
            if not (expired or force_refresh):
                return data["accessToken"]
            body = await asyncio.to_thread(self._token_refresh, data["refreshToken"])
            access, refresh, lifetime = (
                body.get("access_token"),
                body.get("refresh_token"),
                body.get("expires_in"),
            )
            if (
                not isinstance(access, str)
                or not isinstance(refresh, str)
                or not isinstance(lifetime, (int, float))
            ):
                raise ProviderError("Claude token refresh returned an unexpected shape")
            data = {
                **data,
                "accessToken": access,
                "refreshToken": refresh,
                "expiresAt": int(
                    (datetime.now(UTC) + timedelta(seconds=lifetime)).timestamp() * 1000
                ),
            }
            await self._credentials.set_credential(
                ACCOUNT_CREDENTIAL,
                CredentialKind.OAUTH_TOKEN,
                json.dumps({"claudeAiOauth": data}),
            )
            return access

    async def live_allowance(self) -> list[UsageDimension] | None:
        """29.26: current account windows straight from Anthropic, using the
        owner's full-login credential (the session credential cannot read
        usage). None when no account credential is configured; raises
        ProviderError when the reading cannot be obtained."""
        token = await self._account_access_token()
        if token is None:
            return None
        try:
            body = await asyncio.to_thread(self._usage_fetch, token)
        except ProviderError as exc:
            if "HTTP 401" not in str(exc):
                raise
            token = await self._account_access_token(force_refresh=True)
            body = await asyncio.to_thread(self._usage_fetch, token)
        dimensions = _live_allowance_dimensions(body)
        if not dimensions:
            logger.warning(
                "Claude usage response had no recognised windows; keys: %s",
                sorted(body)[:20],
            )
        return dimensions

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

    async def _build(
        self, session: CodingAgentSession, *, prompt: str, resume: bool
    ) -> tuple[ContainerSpec, str]:
        project = await self._projects.get_project(session.project_id)
        if project is None:
            raise ProviderError(f"Unknown project {session.project_id}")
        kind, secret = await self._credential()
        env_var = (
            "ANTHROPIC_API_KEY"
            if kind == CredentialKind.API_KEY
            else "CLAUDE_CODE_OAUTH_TOKEN"
        )

        provider_session_id = (
            session.provider_session_id if resume else str(uuid.uuid4())
        )
        command = ["-p", prompt, "--output-format", "stream-json", "--verbose"]
        command += (
            ["--resume", provider_session_id]
            if resume
            else ["--session-id", provider_session_id]
        )

        read_only = kind == CredentialKind.OAUTH_TOKEN
        if read_only:
            # Hard guardrail — see module docstring. Three independent
            # layers: plan mode, an explicit tool allow/deny pair, and
            # (below) a Docker-enforced read-only mount.
            command += [
                "--permission-mode",
                "plan",
                "--allowedTools",
                *_READ_ONLY_ALLOWED_TOOLS,
                "--disallowedTools",
                *_READ_ONLY_DISALLOWED_TOOLS,
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
            state_volume=f"reachy-claude-state-{session.id}",
        )
        return spec, provider_session_id

    async def start_session(self, session: CodingAgentSession) -> ProviderEvent:
        await self._ensure_can_invoke()
        spec, provider_session_id = await self._build(
            session, prompt=session.task_summary, resume=False
        )
        container_id = await self._runtime.start(spec)
        read_only_note = (
            " (read-only: a Claude Pro/Max subscription credential cannot write yet)"
            if spec.read_only_mount
            else ""
        )
        return ProviderEvent(
            status=CodingAgentStatus.RUNNING,
            summary=f"Claude Code started{read_only_note}",
            provider_session_id=provider_session_id,
            metadata={"container_id": container_id},
        )

    async def resume_session(
        self, session: CodingAgentSession, instruction: str
    ) -> ProviderEvent:
        # The owner's words go to the CLI verbatim as the next user turn.
        if not session.provider_session_id:
            raise ProviderError("No provider session id to resume")
        await self._ensure_can_invoke()
        spec, provider_session_id = await self._build(
            session, prompt=instruction, resume=True
        )
        container_id = await self._runtime.start(spec)
        read_only_note = (
            " (read-only: a Claude Pro/Max subscription credential cannot write yet)"
            if spec.read_only_mount
            else ""
        )
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
            gone = container_status == ContainerStatus.MISSING
            return ProviderEvent(
                status=CodingAgentStatus.LOST,
                summary=(
                    "Claude Code's container no longer exists and no final result was recorded"
                    if gone
                    else "Claude Code's container stopped without producing a final result"
                ),
                provider_session_id=session.provider_session_id,
                metadata={"container_id": session.container_id},
            )

        metadata = {
            "container_id": session.container_id,
            "usage": result.get("usage"),
            "total_cost_usd": result.get("total_cost_usd"),
        }
        if result.get("is_error"):
            return ProviderEvent(
                status=CodingAgentStatus.FAILED,
                summary=(result.get("result") or "Claude Code reported an error")[
                    :2000
                ],
                provider_session_id=session.provider_session_id,
                metadata=metadata,
            )
        status, intervention, source, detail = _classify_intervention(events, result)
        return ProviderEvent(
            status=status,
            summary=(result.get("result") or "Claude Code finished")[:2000],
            provider_session_id=session.provider_session_id,
            metadata=metadata,
            intervention_state=intervention,
            intervention_source=source,
            intervention_detail=detail,
        )

    async def collect_usage(self, session: CodingAgentSession) -> UsageSnapshot:
        dimensions: list[UsageDimension] = []
        if session.container_id:
            events = _parse_stream_json(await self._runtime.logs(session.container_id))
            result = _extract_result(events)
            if result is not None:
                dimensions = _usage_dimensions(result)
            dimensions += _allowance_dimensions(events)
        return UsageSnapshot(
            session_id=session.id, provider="claude-code", dimensions=dimensions
        )
