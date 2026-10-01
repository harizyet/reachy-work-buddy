"""29.1: coding-agent-service app factory. Every dependency is an injectable
kwarg (store, providers, service_token) so tests build this in-process with
ASGITransport and an InMemoryCodingAgentStore + SimulatedProvider, same
pattern as companion-core/reachy-hub's create_app (docs/development.md
testing conventions).
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from coding_agent_service.providers import CodingAgentProvider, SimulatedProvider
from coding_agent_service.routes import install_coding_agent_routes
from coding_agent_service.service import CodingAgentSupervisor
from coding_agent_service.store import CodingAgentStore, InMemoryCodingAgentStore


def create_app(
    *,
    store: CodingAgentStore | None = None,
    providers: dict[str, CodingAgentProvider] | None = None,
    service_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="coding-agent-service")

    resolved_store = store if store is not None else InMemoryCodingAgentStore()
    # 29.3's real ClaudeCodeProvider isn't built yet; "simulated" lets a
    # CodingProject be registered and exercised end to end ahead of that
    # stage without a container. A deployment that enables a real provider
    # registers it under its own name ("claude-code") separately.
    resolved_providers = providers if providers is not None else {"simulated": SimulatedProvider()}
    resolved_token = service_token if service_token is not None else os.environ.get("CODING_AGENT_SERVICE_TOKEN")

    app.state.supervisor = CodingAgentSupervisor(resolved_store, resolved_providers)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    install_coding_agent_routes(app, resolved_token)

    return app


app = create_app()
