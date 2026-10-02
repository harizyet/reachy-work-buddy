"""29.1: coding-agent-service app factory. Every dependency is an injectable
kwarg (store, providers, service_token) so tests build this in-process with
ASGITransport and an InMemoryCodingAgentStore + SimulatedProvider, same
pattern as companion-core/reachy-hub's create_app (docs/development.md
testing conventions).
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from coding_agent_service.claude_provider import ClaudeCodeProvider
from coding_agent_service.credentials import (
    CredentialKeyring,
    CredentialStore,
    EncryptedFileCredentialStore,
    InMemoryCredentialStore,
)
from coding_agent_service.postgres_store import PostgresCodingAgentStore
from coding_agent_service.providers import CodingAgentProvider, SimulatedProvider
from coding_agent_service.reconcile import recover_sessions
from coding_agent_service.routes import install_coding_agent_routes
from coding_agent_service.runtime import ContainerRuntime, DockerCLIContainerRuntime
from coding_agent_service.service import CodingAgentSupervisor
from coding_agent_service.session_poller import run_poll_loop
from coding_agent_service.store import CodingAgentStore, InMemoryCodingAgentStore

logger = logging.getLogger(__name__)


def _default_store() -> CodingAgentStore:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return PostgresCodingAgentStore(dsn)
    logger.warning(
        "DATABASE_URL is not set; coding-agent sessions are kept in memory and are lost when this service restarts"
    )
    return InMemoryCodingAgentStore()


def _default_credential_store() -> CredentialStore:
    key_file = os.environ.get("CODING_AGENT_SECRET_KEY_FILE")
    if not key_file:
        # Dev/test default. A real deployment that wants provider
        # credentials (Claude Code's API key, Codex's, etc.) to survive a
        # restart must set CODING_AGENT_SECRET_KEY_FILE — see
        # credentials.CredentialKeyring.from_file.
        return InMemoryCredentialStore()
    path = os.environ.get(
        "CODING_AGENT_CREDENTIALS_PATH", "/data/coding-agent-credentials.json"
    )
    return EncryptedFileCredentialStore(path, CredentialKeyring.from_file(key_file))


def create_app(
    *,
    store: CodingAgentStore | None = None,
    providers: dict[str, CodingAgentProvider] | None = None,
    service_token: str | None = None,
    credential_store: CredentialStore | None = None,
    container_runtime: ContainerRuntime | None = None,
    terminal_sessions_dir: str | Path | None = None,
    poll_interval_seconds: float | None = None,
) -> FastAPI:
    resolved_store = store if store is not None else _default_store()
    resolved_token = (
        service_token
        if service_token is not None
        else os.environ.get("CODING_AGENT_SERVICE_TOKEN")
    )
    resolved_credentials = (
        credential_store
        if credential_store is not None
        else _default_credential_store()
    )
    resolved_runtime = (
        container_runtime
        if container_runtime is not None
        else DockerCLIContainerRuntime()
    )
    # "simulated" always exists so a CodingProject can be registered and
    # exercised without a container (29.1). "claude-code" is the real
    # adapter (29.3) — constructing it here doesn't touch Docker or the
    # credential store; those calls only happen once a session actually
    # starts, at which point a missing credential or image is reported
    # through the ordinary ProviderError path, not an import-time failure.
    resolved_providers = (
        providers
        if providers is not None
        else {
            "simulated": SimulatedProvider(),
            "claude-code": ClaudeCodeProvider(
                resolved_runtime, resolved_credentials, resolved_store
            ),
        }
    )

    supervisor = CodingAgentSupervisor(resolved_store, resolved_providers)
    # 0 disables background polling; /refresh still works on demand.
    poll_interval = (
        poll_interval_seconds
        if poll_interval_seconds is not None
        else float(os.environ.get("CODING_AGENT_POLL_INTERVAL_SECONDS", "30"))
    )

    # ASGITransport-driven tests skip lifespan and inject stores directly;
    # the production-owned Postgres pool opens and closes here (see
    # docs/development.md testing conventions).
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        opener = getattr(resolved_store, "open", None)
        if opener is not None:
            await opener()
        try:
            if resolved_store.durable:
                report = await recover_sessions(
                    supervisor, resolved_store, resolved_runtime
                )
                _app.state.recovery_report = report
                logger.info(
                    "Session recovery: %d changed, %d unchanged, %d unresolved, %d orphan containers%s",
                    len(report.changed),
                    len(report.unchanged),
                    len(report.unresolved),
                    len(report.orphan_container_ids),
                    f" (skipped: {report.skipped_reason})"
                    if report.skipped_reason
                    else "",
                )
            poller = None
            if poll_interval > 0:
                poller = asyncio.create_task(
                    run_poll_loop(supervisor, resolved_store, poll_interval)
                )
            try:
                yield
            finally:
                if poller is not None:
                    poller.cancel()
                    await asyncio.gather(poller, return_exceptions=True)
        finally:
            closer = getattr(resolved_store, "close", None)
            if closer is not None:
                await closer()

    app = FastAPI(title="coding-agent-service", lifespan=lifespan)
    app.state.supervisor = supervisor
    app.state.credentials = resolved_credentials
    history_dir = (
        terminal_sessions_dir
        if terminal_sessions_dir is not None
        else os.environ.get("TERMINAL_SESSIONS_DIR")
    )
    app.state.terminal_sessions_dir = Path(history_dir) if history_dir else None

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    install_coding_agent_routes(app, resolved_token)

    return app


app = create_app()
