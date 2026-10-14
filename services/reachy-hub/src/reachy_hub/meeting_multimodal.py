"""Owner-only proxy for multimodal meeting intelligence (Phase 53, docs/phase-53.md): attach documents to a meeting, page estimates, the owner's corrections, questions across a
meeting and its documents, and combined findings.

Every route requires the logged-in OWNER SESSION (a cookie whose user is the owner): the REMOTE_UI_TOKEN bearer path is not accepted, because confirming an action creates a task and that
token is a robot-control credential. Every change also requires the CSRF header. The hub is where the trusted access ceiling is established: an owner session is the owner's private web (and
Android) surface, so requests carry `X-Reachy-Access-Ceiling: sensitive`; nothing in a request can change that, and core still checks the meeting and every document's class and project from its
own records. The hub validates a fixed body and forwards it; errors carry fixed messages, never transcript, page or finding text. With core's feature off the config route answers
{"enabled": false} and the others answer 404."""

from __future__ import annotations

from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from reachy_hub.operator import require_csrf
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

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_ID = r"^[A-Za-z0-9_-]{1,64}$"
_KEY = r"^[0-9]{1,6}-[0-9]{1,6}$"
_OWNER_CEILING = {ACCESS_CEILING_HEADER: "sensitive"}
_PASS = (400, 404, 409, 422, 503)


class LinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=64, pattern=_ID)


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern=r"^(confirmed|replaced|no_slide|removed)$")
    document_id: str | None = Field(default=None, max_length=64, pattern=_ID)
    page: int | None = Field(default=None, ge=1, le=1000)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=300)


def install_meeting_multimodal_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]
    owner_change = [Depends(require_owner_session), Depends(require_csrf)]

    async def forward(method: str, path: str, *, json=None, timeout: float = 30.0):
        try:
            response = await core.document_request(method, path, json=json, headers=_OWNER_CEILING, timeout=timeout)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Multimodal meeting intelligence is unavailable") from None
        if response.status_code >= 400:
            if response.status_code in _PASS:
                try:
                    detail = str(response.json().get("detail", "Request refused"))[:200]
                except (ValueError, AttributeError):
                    detail = "Request refused"
                raise HTTPException(response.status_code, detail)
            raise HTTPException(502, "Multimodal meeting intelligence is unavailable")
        return JSONResponse(response.json(), headers=_NO_STORE)

    def m(meeting_id: str) -> str:
        return quote(meeting_id, safe="")

    @app.get(MEETING_MULTIMODAL_CONFIG, dependencies=owner)
    async def config():
        try:
            response = await core.document_request("GET", MEETING_MULTIMODAL_CONFIG, headers=_OWNER_CEILING, timeout=10.0)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Multimodal meeting intelligence is unavailable") from None
        if response.status_code == 404:  # core does not have the feature on
            return JSONResponse({"enabled": False}, headers=_NO_STORE)
        if response.status_code >= 400:
            raise HTTPException(502, "Multimodal meeting intelligence is unavailable")
        return JSONResponse(response.json(), headers=_NO_STORE)

    @app.get(MEETING_MULTIMODAL, dependencies=owner)
    async def overview(meeting_id: str = Path(pattern=_ID)):
        return await forward("GET", f"/meetings/{m(meeting_id)}/multimodal")

    @app.post(MEETING_MULTIMODAL_DOCUMENTS, dependencies=owner_change)
    async def link(body: LinkBody, meeting_id: str = Path(pattern=_ID)):
        return await forward("POST", f"/meetings/{m(meeting_id)}/multimodal/attachments", json=body.model_dump())

    @app.delete(MEETING_MULTIMODAL_DOCUMENT, dependencies=owner_change)
    async def unlink(meeting_id: str = Path(pattern=_ID), attached_id: str = Path(pattern=_ID)):
        return await forward("DELETE", f"/meetings/{m(meeting_id)}/multimodal/attachments/{quote(attached_id, safe='')}")

    @app.post(MEETING_MULTIMODAL_ALIGN, dependencies=owner_change)
    async def align(body: RunBody, meeting_id: str = Path(pattern=_ID)):
        return await forward("POST", f"/meetings/{m(meeting_id)}/multimodal/alignment", json=body.model_dump())

    @app.post(MEETING_MULTIMODAL_ANALYSE, dependencies=owner_change)
    async def analyse(body: RunBody, meeting_id: str = Path(pattern=_ID)):
        return await forward("POST", f"/meetings/{m(meeting_id)}/multimodal/analysis", json=body.model_dump())

    @app.put(MEETING_MULTIMODAL_REVIEW, dependencies=owner_change)
    async def review(body: ReviewBody, meeting_id: str = Path(pattern=_ID), window_key: str = Path(pattern=_KEY)):
        return await forward("PUT", f"/meetings/{m(meeting_id)}/multimodal/windows/{window_key}/review", json=body.model_dump())

    @app.delete(MEETING_MULTIMODAL_REVIEW, dependencies=owner_change)
    async def withdraw(meeting_id: str = Path(pattern=_ID), window_key: str = Path(pattern=_KEY)):
        return await forward("DELETE", f"/meetings/{m(meeting_id)}/multimodal/windows/{window_key}/review")

    @app.post(MEETING_MULTIMODAL_ASK, dependencies=owner_change)
    async def ask(body: AskBody, meeting_id: str = Path(pattern=_ID)):
        return await forward("POST", f"/meetings/{m(meeting_id)}/multimodal/ask", json=body.model_dump(), timeout=180.0)

    @app.post(MEETING_MULTIMODAL_RETRY, dependencies=owner_change)
    async def retry(run_id: str = Path(pattern=_ID)):
        return await forward("POST", f"/meeting-multimodal/runs/{quote(run_id, safe='')}/retry")

    @app.post(MEETING_MULTIMODAL_ACCEPT, dependencies=owner_change)
    async def accept(body: AcceptBody, item_id: str = Path(pattern=_ID)):
        return await forward("POST", f"/meeting-multimodal/items/{quote(item_id, safe='')}/accept", json=body.model_dump(exclude_unset=True), timeout=20.0)

    @app.post(MEETING_MULTIMODAL_DISMISS, dependencies=owner_change)
    async def dismiss(item_id: str = Path(pattern=_ID)):
        return await forward("POST", f"/meeting-multimodal/items/{quote(item_id, safe='')}/dismiss")
