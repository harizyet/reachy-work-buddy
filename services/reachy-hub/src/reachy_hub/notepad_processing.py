"""Owner-only proxy for Notepad processing (Phase 49, docs/phase-49.md): processing status, proposals, review decisions and note-to-meeting links.

Every route requires the logged-in OWNER SESSION (a cookie whose user is the owner): the REMOTE_UI_TOKEN bearer path is not accepted, because accepting a proposal creates tasks
and reminders and that token is a robot-control credential. Every change also requires the CSRF header. The hub validates a fixed body and forwards it; core decides everything
else and the hub adds and removes nothing. Errors carry fixed messages, never note or proposal text. When core has the feature off, the config route answers
{"enabled": false} and the others answer 404."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from reachy_hub.operator import require_csrf
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

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_ID = r"^[A-Za-z0-9_-]{1,64}$"


class EnqueueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)
    include_meetings: bool = False


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=300)
    kind: str | None = Field(default=None, pattern=r"^(task|reminder|event)$")
    due_at: datetime | None = None


class LinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(pattern=r"^(confirmed|rejected)$")


def install_notepad_processing_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]
    owner_change = [Depends(require_owner_session), Depends(require_csrf)]

    async def forward(call):
        try:
            return JSONResponse(await call(), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (404, 409, 422, 503):
                try:
                    detail = str(exc.response.json().get("detail", "Request refused"))[:200]
                except (ValueError, AttributeError):
                    detail = "Request refused"
                raise HTTPException(status, detail) from None
            raise HTTPException(502, "Notepad processing unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Notepad processing unavailable") from None

    @app.get(NOTEPAD_PROCESSING_CONFIG, dependencies=owner)
    async def config():
        try:
            return JSONResponse(await core.planner_request("GET", NOTEPAD_PROCESSING_CONFIG), headers=_NO_STORE)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:  # core does not have the feature on
                return JSONResponse({"enabled": False}, headers=_NO_STORE)
            raise HTTPException(502, "Notepad processing unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Notepad processing unavailable") from None

    @app.get(NOTE_PROCESSING, dependencies=owner)
    async def status(note_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("GET", f"/notes/{quote(note_id, safe='')}/processing"))

    @app.post(NOTE_PROCESSING, dependencies=owner_change)
    async def enqueue(body: EnqueueBody, note_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("POST", f"/notes/{quote(note_id, safe='')}/processing", json=body.model_dump(), timeout=20.0))

    @app.get(NOTE_MEETING_LINKS, dependencies=owner)
    async def meeting_links(note_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("GET", f"/notes/{quote(note_id, safe='')}/meeting-links", timeout=30.0))

    @app.put(NOTE_MEETING_LINK, dependencies=owner_change)
    async def set_meeting_link(body: LinkBody, note_id: str = Path(pattern=_ID), meeting_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("PUT", f"/notes/{quote(note_id, safe='')}/meeting-links/{quote(meeting_id, safe='')}", json=body.model_dump(), timeout=30.0))

    @app.post(NOTEPAD_JOB_RETRY, dependencies=owner_change)
    async def retry(job_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("POST", f"/notepad-processing/jobs/{quote(job_id, safe='')}/retry"))

    @app.get(NOTEPAD_PROPOSALS, dependencies=owner)
    async def proposals():
        return await forward(lambda: core.planner_request("GET", NOTEPAD_PROPOSALS))

    @app.post(NOTEPAD_PROPOSAL_ACCEPT, dependencies=owner_change)
    async def accept(body: AcceptBody, proposal_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("POST", f"/notepad-proposals/{quote(proposal_id, safe='')}/accept", json=body.model_dump(exclude_unset=True, mode="json"), timeout=20.0))

    @app.post(NOTEPAD_PROPOSAL_DISMISS, dependencies=owner_change)
    async def dismiss(proposal_id: str = Path(pattern=_ID)):
        return await forward(lambda: core.planner_request("POST", f"/notepad-proposals/{quote(proposal_id, safe='')}/dismiss"))
