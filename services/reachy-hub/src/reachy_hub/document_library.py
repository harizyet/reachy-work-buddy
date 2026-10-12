"""Owner-only proxy for the document library (Phase 50J, docs/phase-50.md): upload, catalogue, reprocess, read, search, summaries and deletion.

Every route needs the logged-in OWNER SESSION (cookie whose user is the owner; the REMOTE_UI_TOKEN bearer is a robot-control credential and is not accepted) and every change also needs the
CSRF header. The hub is where the trusted access ceiling is established: an owner session is the owner's private web (and Android) surface, so content routes ask core with
`X-Reachy-Access-Ceiling: sensitive`; nothing in a request can change that, and core still checks every document's class and project from its own record. The hub validates a fixed
shape and forwards it; errors carry fixed messages, never filenames or document text. When core has the library off, the config route says so and the others answer 404."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import Depends, File, Form, HTTPException, Path, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from reachy_hub.operator import require_csrf
from shared.protocols.document_library_api import (
    ACCESS_CEILING_HEADER,
    DOCUMENT_LIBRARY_CONFIG,
    DOCUMENT_LIBRARY_DOCUMENT,
    DOCUMENT_LIBRARY_DOCUMENTS,
    DOCUMENT_LIBRARY_LOCATOR,
    DOCUMENT_LIBRARY_READ,
    DOCUMENT_LIBRARY_REPROCESS,
    DOCUMENT_LIBRARY_SEARCH,
    DOCUMENT_LIBRARY_SUMMARIES,
)

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_ID = r"^[A-Za-z0-9_-]{1,64}$"
_OWNER_CEILING = {ACCESS_CEILING_HEADER: "sensitive"}
_PASS = (400, 403, 404, 409, 413, 415, 422, 502, 503)


class PatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    project_scope: str | None = Field(default=None, max_length=100)
    sensitivity: str | None = Field(default=None, pattern=r"^(public|work-private|sensitive)$")
    processing_priority: str | None = Field(default=None, pattern=r"^(background|normal|interactive)$")


class ReprocessBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: str | None = Field(default=None, pattern=r"^(flash|basic|standard|advanced)$")


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)


class SummaryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: str = Field(default="ordinary", pattern=r"^(ordinary|executive|technical)$")
    force: bool = False


def install_document_library_routes(app, require_owner_session, core) -> None:
    owner = [Depends(require_owner_session)]
    owner_change = [Depends(require_owner_session), Depends(require_csrf)]

    async def forward(method: str, path: str, *, json=None, params=None, data=None, files=None, timeout: float = 30.0):
        try:
            response = await core.document_request(method, path, json=json, params=params, data=data, files=files, headers=_OWNER_CEILING, timeout=timeout)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "The document library is unavailable") from None
        if response.status_code == 204:
            return Response(status_code=204, headers=_NO_STORE)
        if response.status_code >= 400:
            if response.status_code in _PASS:
                try:
                    detail = str(response.json().get("detail", "Request refused"))[:200]
                except (ValueError, AttributeError):
                    detail = "Request refused"
                raise HTTPException(response.status_code, detail)
            raise HTTPException(502, "The document library is unavailable")
        return JSONResponse(response.json(), status_code=response.status_code, headers=_NO_STORE)

    def doc(document_id: str) -> str:
        return quote(document_id, safe="")

    @app.get(DOCUMENT_LIBRARY_CONFIG, dependencies=owner)
    async def config():
        try:
            response = await core.document_request("GET", DOCUMENT_LIBRARY_CONFIG)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "The document library is unavailable") from None
        if response.status_code == 404:  # core does not have the library on
            return JSONResponse({"enabled": False}, headers=_NO_STORE)
        return JSONResponse(response.json(), headers=_NO_STORE)

    @app.get(DOCUMENT_LIBRARY_DOCUMENTS, dependencies=owner)
    async def list_documents():
        return await forward("GET", DOCUMENT_LIBRARY_DOCUMENTS)

    @app.post(DOCUMENT_LIBRARY_DOCUMENTS, dependencies=owner_change)
    async def upload(
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form(max_length=200)] = None,
        sensitivity: Annotated[str | None, Form(pattern=r"^(public|work-private|sensitive)$")] = None,
        project_scope: Annotated[str | None, Form(max_length=100)] = None,
        processing_priority: Annotated[str, Form(pattern=r"^(background|normal|interactive)$")] = "background",
    ):
        data = {k: v for k, v in {"title": title, "sensitivity": sensitivity, "project_scope": project_scope, "processing_priority": processing_priority}.items() if v}
        return await forward(
            "POST", DOCUMENT_LIBRARY_DOCUMENTS, data=data, files={"file": (file.filename or "", await file.read(), "application/octet-stream")}, timeout=180.0
        )

    @app.get(DOCUMENT_LIBRARY_DOCUMENT, dependencies=owner)
    async def detail(document_id: str = Path(pattern=_ID)):
        return await forward("GET", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}")

    @app.patch(DOCUMENT_LIBRARY_DOCUMENT, dependencies=owner_change)
    async def patch(body: PatchBody, document_id: str = Path(pattern=_ID)):
        return await forward("PATCH", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}", json=body.model_dump(exclude_unset=True))

    @app.delete(DOCUMENT_LIBRARY_DOCUMENT, dependencies=owner_change)
    async def delete(document_id: str = Path(pattern=_ID)):
        return await forward("DELETE", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}", timeout=120.0)

    @app.post(DOCUMENT_LIBRARY_REPROCESS, dependencies=owner_change)
    async def reprocess(body: ReprocessBody | None = None, document_id: str = Path(pattern=_ID)):
        return await forward("POST", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}/reprocess", json=(body or ReprocessBody()).model_dump(exclude_unset=True), timeout=60.0)

    @app.get(DOCUMENT_LIBRARY_READ, dependencies=owner)
    async def read(
        document_id: str = Path(pattern=_ID),
        page_range: str | None = Query(default=None, max_length=64, pattern=r"^\d+(-\d+)?(,\d+(-\d+)?)*$"),
        after: str | None = Query(default=None, max_length=256),
        limit: int = Query(default=8000, ge=500, le=30000),
    ):
        params = {k: v for k, v in {"page_range": page_range, "after": after, "limit": limit}.items() if v is not None}
        return await forward("GET", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}/read", params=params, timeout=60.0)

    @app.get(DOCUMENT_LIBRARY_LOCATOR, dependencies=owner)
    async def locator(document_id: str = Path(pattern=_ID), locator: str = Query(max_length=256), context: int = Query(default=0, ge=0, le=3), limit: int = Query(default=8000, ge=500, le=30000)):
        return await forward("GET", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}/locator", params={"locator": locator, "context": context, "limit": limit}, timeout=60.0)

    @app.post(DOCUMENT_LIBRARY_SEARCH, dependencies=owner_change)
    async def search(body: SearchBody, document_id: str = Path(pattern=_ID)):
        return await forward("POST", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}/search", json=body.model_dump(), timeout=60.0)

    @app.get(DOCUMENT_LIBRARY_SUMMARIES, dependencies=owner)
    async def summaries(document_id: str = Path(pattern=_ID)):
        return await forward("GET", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}/summaries")

    @app.post(DOCUMENT_LIBRARY_SUMMARIES, dependencies=owner_change)
    async def summarize(body: SummaryBody | None = None, document_id: str = Path(pattern=_ID)):
        return await forward("POST", f"{DOCUMENT_LIBRARY_DOCUMENTS}/{doc(document_id)}/summaries", json=(body or SummaryBody()).model_dump(), timeout=30.0)
