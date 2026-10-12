"""Core routes for meeting analysis (Phase 31). Registered only when MEETING_ANALYSIS_ENABLED is true; otherwise they do not exist (404).

They sit behind the service-token middleware like every other core route, so only the hub can reach them; the hub proxies them for the OWNER SESSION only (cookie plus CSRF for every
change). Nothing here is reachable from /conversation. Errors carry a fixed message and never transcript or item text."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from companion_core.meeting_analysis.models import MAX_TEXT
from companion_core.meeting_analysis.service import (
    AnalysisError,
    MeetingAnalysisService,
)
from shared.protocols.meeting_analysis_api import (
    MEETING_ANALYSIS,
    MEETING_ANALYSIS_ACCEPT,
    MEETING_ANALYSIS_CONFIG,
    MEETING_ANALYSIS_DISMISS,
    MEETING_ANALYSIS_ITEMS,
    MEETING_ANALYSIS_PROVENANCE,
    MEETING_ANALYSIS_RETRY,
)


class EnqueueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False  # an explicit re-analysis of a transcript that was already analysed
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)  # the hash of the transcript the owner is looking at; a different current one is refused


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=MAX_TEXT)


def install_meeting_analysis_routes(app: FastAPI) -> None:
    def service() -> MeetingAnalysisService:
        svc = getattr(app.state, "meeting_analysis_service", None)
        if svc is None:
            raise HTTPException(503, "Meeting analysis is unavailable")
        return svc

    async def run(call):
        try:
            return await call
        except AnalysisError as exc:
            raise HTTPException(exc.status, exc.detail) from None

    @app.get(MEETING_ANALYSIS_CONFIG)
    async def config() -> dict:
        return {"enabled": getattr(app.state, "meeting_analysis_service", None) is not None}

    @app.get(MEETING_ANALYSIS)
    async def meeting_status(meeting_id: str) -> dict:
        return await run(service().status(meeting_id))

    @app.post(MEETING_ANALYSIS)
    async def enqueue(meeting_id: str, body: EnqueueBody | None = None) -> dict:
        body = body or EnqueueBody()
        return await run(service().enqueue(meeting_id, force=body.force, expected_hash=body.expected_hash))

    @app.post(MEETING_ANALYSIS_RETRY)
    async def retry(run_id: str) -> dict:
        return await run(service().retry(run_id))

    @app.get(MEETING_ANALYSIS_ITEMS)
    async def pending() -> dict:
        return await service().pending()

    @app.post(MEETING_ANALYSIS_ACCEPT)
    async def accept(item_id: str, body: AcceptBody | None = None) -> dict:
        return await run(service().accept(item_id, text=(body or AcceptBody()).text))

    @app.post(MEETING_ANALYSIS_DISMISS)
    async def dismiss(item_id: str) -> dict:
        return await run(service().dismiss(item_id))

    @app.get(MEETING_ANALYSIS_PROVENANCE)
    async def provenance(record_id: str) -> dict:
        found = await service().provenance(record_id)
        if found is None:
            raise HTTPException(404, "This task was not made from a meeting")
        return found
