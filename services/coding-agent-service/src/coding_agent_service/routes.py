"""29.1: thin HTTP translation over CodingAgentSupervisor. Same shape as
companion-core's accounts/routes.py — a require_service dependency gate
plus one handler per route, no business logic here.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request

from coding_agent_service.credentials import CredentialStore
from coding_agent_service.providers import ProviderError, ProviderInvocationBlockedError
from coding_agent_service.service import (
    CodingAgentSupervisor,
    SessionNotResumableError,
    UnknownProjectError,
    UnknownProviderError,
    UnknownSessionError,
)
from shared.models.coding_agent import (
    CodingProject,
    CreateProjectRequest,
    ResumeSessionRequest,
    SendInputRequest,
    SetCredentialRequest,
    StartSessionRequest,
)
from shared.protocols import coding_agent as paths


def install_coding_agent_routes(app, service_token: str | None) -> None:
    async def require_service(request: Request) -> None:
        incoming = request.headers.get(paths.SERVICE_HEADER, "")
        if not service_token or not secrets.compare_digest(incoming, service_token):
            raise HTTPException(401, "Service authentication required")

    dependencies = [Depends(require_service)]

    def supervisor() -> CodingAgentSupervisor:
        return app.state.supervisor

    def credentials() -> CredentialStore:
        return app.state.credentials

    @app.post(paths.PROJECTS, dependencies=dependencies)
    async def create_project(body: CreateProjectRequest):
        project = CodingProject(**body.model_dump())
        return await supervisor().add_project(project)

    @app.get(paths.PROJECTS, dependencies=dependencies)
    async def list_projects():
        return await supervisor().list_projects()

    @app.get(paths.PROJECT, dependencies=dependencies)
    async def get_project(project_id: str):
        try:
            return await supervisor().get_project(project_id)
        except UnknownProjectError:
            raise HTTPException(404, "Unknown project") from None

    @app.post(paths.SESSIONS, dependencies=dependencies)
    async def start_session(body: StartSessionRequest):
        try:
            return await supervisor().start_session(
                project_id=body.project_id,
                task_summary=body.task_summary,
                owner_user_id=body.owner_user_id,
                branch=body.branch,
            )
        except UnknownProjectError:
            raise HTTPException(404, "Unknown project") from None
        except UnknownProviderError as exc:
            raise HTTPException(400, f"Unknown provider: {exc}") from None
        except ProviderInvocationBlockedError as exc:
            raise HTTPException(403, str(exc)) from None
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get(paths.SESSIONS, dependencies=dependencies)
    async def list_sessions():
        return await supervisor().list_sessions()

    @app.get(paths.SESSION, dependencies=dependencies)
    async def get_session(session_id: str):
        try:
            return await supervisor().get_session(session_id)
        except UnknownSessionError:
            raise HTTPException(404, "Unknown session") from None

    @app.post(paths.SESSION_RESUME, dependencies=dependencies)
    async def resume_session(session_id: str, body: ResumeSessionRequest):
        try:
            return await supervisor().resume_session(session_id, body.instruction)
        except UnknownSessionError:
            raise HTTPException(404, "Unknown session") from None
        except SessionNotResumableError as exc:
            raise HTTPException(409, str(exc)) from None
        except ProviderInvocationBlockedError as exc:
            raise HTTPException(403, str(exc)) from None
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post(paths.SESSION_INPUT, dependencies=dependencies)
    async def send_input(session_id: str, body: SendInputRequest):
        try:
            return await supervisor().send_input(session_id, body.text)
        except UnknownSessionError:
            raise HTTPException(404, "Unknown session") from None
        except SessionNotResumableError as exc:
            raise HTTPException(409, str(exc)) from None
        except ProviderInvocationBlockedError as exc:
            raise HTTPException(403, str(exc)) from None
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post(paths.SESSION_STOP, dependencies=dependencies)
    async def stop_session(session_id: str):
        try:
            return await supervisor().stop_session(session_id)
        except UnknownSessionError:
            raise HTTPException(404, "Unknown session") from None
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post(paths.SESSION_REFRESH, dependencies=dependencies)
    async def refresh_session(session_id: str):
        try:
            return await supervisor().inspect_session(session_id)
        except UnknownSessionError:
            raise HTTPException(404, "Unknown session") from None
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get(paths.SESSION_EVENTS, dependencies=dependencies)
    async def list_events(session_id: str):
        try:
            return await supervisor().list_events(session_id)
        except UnknownSessionError:
            raise HTTPException(404, "Unknown session") from None

    @app.get(paths.SESSION_USAGE, dependencies=dependencies)
    async def get_usage(session_id: str):
        try:
            return await supervisor().collect_usage(session_id)
        except UnknownSessionError:
            raise HTTPException(404, "Unknown session") from None

    @app.get(paths.PROVIDER_CAPABILITIES, dependencies=dependencies)
    async def provider_capabilities(provider: str):
        try:
            return supervisor().provider_capabilities(provider)
        except UnknownProviderError:
            raise HTTPException(404, "Unknown provider") from None

    @app.get(paths.PROVIDER_ALLOWANCE, dependencies=dependencies)
    async def provider_allowance(provider: str):
        try:
            return await supervisor().provider_allowance(provider)
        except UnknownProviderError:
            raise HTTPException(404, "Unknown provider") from None

    @app.get(paths.PROVIDER_CREDENTIALS, dependencies=dependencies)
    async def list_credentials():
        return await credentials().list_records()

    @app.get(paths.PROVIDER_CREDENTIAL, dependencies=dependencies)
    async def get_credential(provider: str):
        record = await credentials().describe(provider)
        if record is None:
            raise HTTPException(404, "No credential configured for this provider")
        return record

    @app.put(paths.PROVIDER_CREDENTIAL, dependencies=dependencies)
    async def set_credential(provider: str, body: SetCredentialRequest):
        return await credentials().set_credential(provider, body.kind, body.value)

    @app.delete(paths.PROVIDER_CREDENTIAL, dependencies=dependencies)
    async def delete_credential(provider: str):
        await credentials().clear_credential(provider)
        return {"status": "cleared"}
