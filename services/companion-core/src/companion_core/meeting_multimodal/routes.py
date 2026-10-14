"""Core routes for multimodal meeting intelligence (Phase 53). Registered only when MEETING_MULTIMODAL_ENABLED is true and the document library is on; otherwise they do not exist (404).

They sit behind the service-token middleware like every other core route, so only the hub can reach them; the hub proxies them for the OWNER SESSION only (cookie plus CSRF for every
change) and sets the trusted access ceiling. Nothing here is reachable from /conversation. Errors carry a fixed message and never transcript, page or finding text."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from companion_core.document_library.access import access_from_ceiling
from companion_core.meeting_multimodal.models import MAX_TEXT
from companion_core.meeting_multimodal.service import (
    MeetingMultimodalService,
    MultimodalError,
)
from shared.protocols.document_library_api import ACCESS_CEILING_HEADER
from shared.protocols.meeting_multimodal_api import (
    MEETING_MULTIMODAL,
    MEETING_MULTIMODAL_ACCEPT,
    MEETING_MULTIMODAL_ALIGN,
    MEETING_MULTIMODAL_ANALYSE,
    MEETING_MULTIMODAL_ASK,
    MEETING_MULTIMODAL_CONFIG,
    MEETING_MULTIMODAL_DISMISS,
    MEETING_MULTIMODAL_DOCUMENT,
    MEETING_MULTIMODAL_DOCUMENTS,
    MEETING_MULTIMODAL_RETRY,
    MEETING_MULTIMODAL_REVIEW,
)


class LinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern=r"^(confirmed|replaced|no_slide|removed)$")
    document_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    page: int | None = Field(default=None, ge=1, le=1000)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=MAX_TEXT)


def install_meeting_multimodal_routes(app: FastAPI) -> None:
    def service() -> MeetingMultimodalService:
        svc = getattr(app.state, "meeting_multimodal_service", None)
        if svc is None:
            raise HTTPException(503, "Multimodal meeting intelligence is unavailable")
        return svc

    def access_of(header: str | None):
        try:
            return access_from_ceiling(header)
        except ValueError:
            raise HTTPException(400, "Unknown access ceiling") from None

    async def run(call):
        try:
            return await call
        except MultimodalError as exc:
            raise HTTPException(exc.status, exc.detail) from None

    @app.get(MEETING_MULTIMODAL_CONFIG)
    async def config() -> dict:
        return {"enabled": getattr(app.state, "meeting_multimodal_service", None) is not None}

    @app.get(MEETING_MULTIMODAL)
    async def overview(meeting_id: str, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().overview(meeting_id, access_of(ceiling)))

    @app.post(MEETING_MULTIMODAL_DOCUMENTS)
    async def link(meeting_id: str, body: LinkBody, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().link(meeting_id, body.document_id, access_of(ceiling)))

    @app.delete(MEETING_MULTIMODAL_DOCUMENT)
    async def unlink(meeting_id: str, document_id: str, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().unlink(meeting_id, document_id, access_of(ceiling)))

    @app.post(MEETING_MULTIMODAL_ALIGN)
    async def align(meeting_id: str, body: RunBody | None = None, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        body = body or RunBody()
        return await run(service().enqueue_alignment(meeting_id, access_of(ceiling), force=body.force, expected_hash=body.expected_hash))

    @app.post(MEETING_MULTIMODAL_ANALYSE)
    async def analyse(meeting_id: str, body: RunBody | None = None, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().enqueue_analysis(meeting_id, access_of(ceiling), force=(body or RunBody()).force))

    @app.put(MEETING_MULTIMODAL_REVIEW)
    async def review(meeting_id: str, window_key: str, body: ReviewBody, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().review(meeting_id, window_key, access_of(ceiling), decision=body.decision, document_id=body.document_id, page=body.page))

    @app.delete(MEETING_MULTIMODAL_REVIEW)
    async def withdraw(meeting_id: str, window_key: str, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().clear_review(meeting_id, window_key, access_of(ceiling)))

    @app.post(MEETING_MULTIMODAL_ASK)
    async def ask(meeting_id: str, body: AskBody, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().ask(meeting_id, access_of(ceiling), body.question))

    @app.post(MEETING_MULTIMODAL_RETRY)
    async def retry(run_id: str, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().retry(run_id, access_of(ceiling)))

    @app.post(MEETING_MULTIMODAL_ACCEPT)
    async def accept(item_id: str, body: AcceptBody | None = None, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().accept(item_id, access_of(ceiling), text=(body or AcceptBody()).text))

    @app.post(MEETING_MULTIMODAL_DISMISS)
    async def dismiss(item_id: str, ceiling: str | None = Header(default=None, alias=ACCESS_CEILING_HEADER)) -> dict:
        return await run(service().dismiss(item_id, access_of(ceiling)))
