"""Owner-only transport for coding-agent-service's provider credentials
(Phase 29.19, docs/phase-29.md). Same owner-cookie+CSRF shape as
reachy_hub.accounts.install_accounts — never a bearer-token path, since
entering a provider secret is exactly the kind of action AGENTS.md's
"preserve owner-cookie/CSRF plus bearer access" expects to require the
stronger of the two.
"""

from __future__ import annotations

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from reachy_hub.coding_agent_client import CodingAgentServiceClient
from reachy_hub.operator import require_csrf
from shared.models.coding_agent import (
    CreateProjectRequest,
    SetCredentialRequest,
    StartSessionRequest,
)
from shared.protocols import coding_agent as paths


# 29.3/29.25: the only providers that can ever need an owner-entered
# credential. "simulated" (providers.SimulatedProvider) never does, so it
# is deliberately not offered here — there is nothing for the owner to set.
# "claude-code-account" is the read-only full-login credential used only to read
# the live allowance (claude_provider.ACCOUNT_CREDENTIAL).
class DashboardStartSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    task_summary: str = Field(min_length=1, max_length=4000)
    branch: str | None = Field(default=None, max_length=200)


KNOWN_CREDENTIAL_PROVIDERS = frozenset({"claude-code", "claude-code-account", "codex"})


def install_coding_agent_credentials(
    app, client: CodingAgentServiceClient, *, enabled: bool, owner_user_id: str = "default-user"
) -> None:
    async def owner(request: Request) -> None:
        username = await app.state.user_store.owner() if getattr(app.state, "user_store", None) else None
        if not enabled:
            raise HTTPException(503, "Coding agent supervisor is not configured on this installation")
        if not username or request.scope.get("session", {}).get("user") != username:
            raise HTTPException(401, "Login required")
        if request.method not in {"GET", "HEAD"}:
            require_csrf(request)

    dependencies = [Depends(owner)]

    def _validate_provider(provider: str) -> None:
        if provider not in KNOWN_CREDENTIAL_PROVIDERS:
            raise HTTPException(404, "Unknown coding-agent provider")

    @app.get(paths.PROVIDER_CREDENTIALS, dependencies=dependencies)
    async def list_credentials():
        try:
            return await client.list_credentials()
        except httpx.HTTPError:
            raise HTTPException(502, "Coding agent service unavailable") from None

    @app.get(paths.PROVIDER_CREDENTIAL, dependencies=dependencies)
    async def get_credential(provider: str):
        _validate_provider(provider)
        try:
            record = await client.get_credential(provider)
        except httpx.HTTPError:
            raise HTTPException(502, "Coding agent service unavailable") from None
        if record is None:
            raise HTTPException(404, "No credential configured")
        return record

    @app.put(paths.PROVIDER_CREDENTIAL, dependencies=dependencies)
    async def set_credential(provider: str, body: SetCredentialRequest):
        _validate_provider(provider)
        try:
            return await client.set_credential(provider, body.kind.value, body.value)
        except httpx.HTTPStatusError:
            raise HTTPException(400, "Invalid credential") from None
        except httpx.HTTPError:
            raise HTTPException(502, "Coding agent service unavailable") from None

    @app.delete(paths.PROVIDER_CREDENTIAL, dependencies=dependencies)
    async def clear_credential(provider: str):
        _validate_provider(provider)
        try:
            return await client.clear_credential(provider)
        except httpx.HTTPError:
            raise HTTPException(502, "Coding agent service unavailable") from None


    # Phase 29.22: the dashboard. Same owner gate; a thin pass-through whose
    # only job is turning service failures into owner-readable errors.
    prefix = "/coding-agents"

    async def call(coro):
        try:
            return await coro
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (400, 403, 404, 409):
                try:
                    detail = exc.response.json().get("detail", "Request refused")
                except ValueError:
                    detail = "Request refused"
                raise HTTPException(status, detail if isinstance(detail, str) else "Invalid request") from None
            if status == 422:
                raise HTTPException(400, "Invalid request") from None
            raise HTTPException(502, "Coding agent service unavailable") from None
        except httpx.HTTPError:
            raise HTTPException(502, "Coding agent service unavailable") from None

    @app.get(prefix + "/projects", dependencies=dependencies)
    async def dashboard_projects():
        return await call(client.list_projects())

    @app.post(prefix + "/projects", dependencies=dependencies)
    async def dashboard_create_project(body: CreateProjectRequest):
        return await call(client.create_project(body.model_dump()))

    @app.get(prefix + "/sessions", dependencies=dependencies)
    async def dashboard_sessions():
        return await call(client.list_sessions())

    @app.post(prefix + "/sessions", dependencies=dependencies)
    async def dashboard_start_session(body: DashboardStartSession):
        # The owner id is the installation's, never browser-supplied.
        request = StartSessionRequest(
            project_id=body.project_id, task_summary=body.task_summary,
            owner_user_id=owner_user_id, branch=body.branch,
        )
        return await call(client.start_session(request.model_dump()))

    @app.post(prefix + "/sessions/{session_id}/stop", dependencies=dependencies)
    async def dashboard_stop_session(session_id: str):
        return await call(client.stop_session(session_id))

    @app.post(prefix + "/sessions/{session_id}/refresh", dependencies=dependencies)
    async def dashboard_refresh_session(session_id: str):
        return await call(client.refresh_session(session_id))

    @app.get(prefix + "/sessions/{session_id}/events", dependencies=dependencies)
    async def dashboard_session_events(session_id: str):
        return await call(client.session_events(session_id))

    @app.get(prefix + "/sessions/{session_id}/usage", dependencies=dependencies)
    async def dashboard_session_usage(session_id: str):
        return await call(client.session_usage(session_id))

    @app.get(prefix + "/terminal-sessions", dependencies=dependencies)
    async def dashboard_terminal_sessions():
        return await call(client.terminal_sessions())

    @app.get(prefix + "/allowance/{provider}", dependencies=dependencies)
    async def dashboard_allowance(provider: str):
        return await call(client.provider_allowance(provider))
