"""Core routes for Notepad processing (Phase 49). Registered only when NOTEPAD_PROCESSING_ENABLED is true; otherwise they do not exist (404).

They sit behind the service-token middleware like every other core route, so only the hub can reach them; the hub proxies them for the OWNER SESSION only (cookie plus CSRF for every
change). Nothing here is reachable from /conversation. Errors carry a fixed message and never note or proposal text."""

from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from companion_core.notepad_processing.models import MAX_TEXT, Kind
from companion_core.notepad_processing.service import (
    UNSET,
    NotepadError,
    NotepadService,
)
from shared.protocols.notepad_processing_api import (
    NOTE_MEETING_LINK,
    NOTE_MEETING_LINKS,
    NOTE_PROCESSING,
    NOTEPAD_JOB_RETRY,
    NOTEPAD_PROCESSING_CONFIG,
    NOTEPAD_PROPOSAL_ACCEPT,
    NOTEPAD_PROPOSAL_DISMISS,
    NOTEPAD_PROPOSALS,
)


class EnqueueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False  # an explicit reprocess of text that was already processed
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)  # the hash of the text the owner saved; a different current text is refused
    include_meetings: bool = False  # also use the transcripts of this note's CONFIRMED linked meetings (an explicit choice, per request)


class LinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(pattern="^(confirmed|rejected)$")


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=MAX_TEXT)
    kind: Kind | None = None
    due_at: datetime | None = None


def install_notepad_routes(app: FastAPI) -> None:
    def service() -> NotepadService:
        svc = getattr(app.state, "notepad_service", None)
        if svc is None:
            raise HTTPException(503, "Notepad processing is unavailable")
        return svc

    async def run(call):
        try:
            return await call
        except NotepadError as exc:
            raise HTTPException(exc.status, exc.detail) from None

    @app.get(NOTEPAD_PROCESSING_CONFIG)
    async def config() -> dict:
        return {"enabled": getattr(app.state, "notepad_service", None) is not None}

    @app.get(NOTE_PROCESSING)
    async def note_status(note_id: str) -> dict:
        return await run(service().status(note_id))

    @app.post(NOTE_PROCESSING)
    async def enqueue(note_id: str, body: EnqueueBody | None = None) -> dict:
        body = body or EnqueueBody()
        return await run(service().enqueue(note_id, force=body.force, expected_hash=body.expected_hash, include_meetings=body.include_meetings))

    @app.get(NOTE_MEETING_LINKS)
    async def meeting_links(note_id: str) -> dict:
        return await run(service().links_for(note_id))

    @app.put(NOTE_MEETING_LINK)
    async def set_meeting_link(note_id: str, meeting_id: str, body: LinkBody) -> dict:
        return await run(service().set_link(note_id, meeting_id, body.state))

    @app.post(NOTEPAD_JOB_RETRY)
    async def retry(job_id: str) -> dict:
        return await run(service().retry(job_id))

    @app.get(NOTEPAD_PROPOSALS)
    async def pending() -> dict:
        return await service().pending()

    @app.post(NOTEPAD_PROPOSAL_ACCEPT)
    async def accept(proposal_id: str, body: AcceptBody | None = None) -> dict:
        body = body or AcceptBody()
        given = body.model_fields_set
        return await run(service().accept(proposal_id, text=body.text, kind=body.kind, due_at=body.due_at if "due_at" in given else UNSET))

    @app.post(NOTEPAD_PROPOSAL_DISMISS)
    async def dismiss(proposal_id: str) -> dict:
        return await run(service().dismiss(proposal_id))
