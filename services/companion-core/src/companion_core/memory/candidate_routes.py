"""Core routes for reviewing memory candidates (Phase 44F). Registered only when MEMORY_CANDIDATES_ENABLED is true; otherwise they do not exist (404).

They sit behind the service-token middleware like every other core route, so only the hub can reach them; the hub proxies them for the OWNER SESSION only (cookie plus CSRF for every change,
no bearer-token path). Nothing here is reachable from /conversation, so a spoken turn cannot list, accept or reject anything. Errors carry a fixed message and never the candidate text."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from companion_core.memory.candidate_service import (
    UNSET,
    CandidateError,
    CandidateService,
)
from shared.models.memory import MemoryType
from shared.models.response import Privacy
from shared.protocols.memory_candidates_api import (
    MEMORY_CANDIDATE_ACCEPT,
    MEMORY_CANDIDATE_REJECT,
    MEMORY_CANDIDATES,
    MEMORY_CANDIDATES_FORGET_CONVERSATION,
)


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=400)
    type: MemoryType | None = None
    project_scope: str | None = Field(default=None, max_length=64)
    sensitivity: Privacy | None = None
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    acknowledge_lower: bool = False


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suppress: bool = False


class ForgetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=200)


def install_candidate_routes(app: FastAPI, *, capture_on: bool) -> None:
    def service() -> CandidateService:
        svc = getattr(app.state, "candidate_service", None)
        if svc is None:
            raise HTTPException(503, "Memory suggestions are unavailable")
        return svc

    async def run(call):
        try:
            return await call
        except CandidateError as exc:
            raise HTTPException(exc.status, exc.detail) from None

    @app.get(MEMORY_CANDIDATES)
    async def list_candidates() -> dict:
        return {"candidates": await service().list(), "capture_enabled": capture_on and getattr(app.state, "candidate_capture", None) is not None}

    @app.post(MEMORY_CANDIDATES_FORGET_CONVERSATION)
    async def forget_conversation(body: ForgetBody) -> dict:
        return await run(service().forget_conversation(body.conversation_id))

    @app.post(MEMORY_CANDIDATE_ACCEPT)
    async def accept(candidate_id: str, body: AcceptBody) -> dict:
        given = body.model_fields_set
        return await run(service().accept(
            candidate_id, text=body.text, type=body.type, scope=body.project_scope if "project_scope" in given else UNSET, sensitivity=body.sensitivity,
            expires_in_days=body.expires_in_days if "expires_in_days" in given else UNSET, acknowledge_lower=body.acknowledge_lower))

    @app.post(MEMORY_CANDIDATE_REJECT)
    async def reject(candidate_id: str, body: RejectBody) -> dict:
        return await run(service().reject(candidate_id, suppress=body.suppress))
