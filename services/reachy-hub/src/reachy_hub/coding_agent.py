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

from reachy_hub.coding_agent_client import CodingAgentServiceClient
from reachy_hub.operator import require_csrf
from shared.models.coding_agent import SetCredentialRequest
from shared.protocols import coding_agent as paths

# 29.3/29.25: the only providers that can ever need an owner-entered
# credential. "simulated" (providers.SimulatedProvider) never does, so it
# is deliberately not offered here — there is nothing for the owner to set.
KNOWN_CREDENTIAL_PROVIDERS = frozenset({"claude-code", "codex"})


def install_coding_agent_credentials(app, client: CodingAgentServiceClient, *, enabled: bool) -> None:
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
