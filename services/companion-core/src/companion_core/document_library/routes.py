"""Core routes for the document library (Phase 50B). Registered only when DOCUMENT_LIBRARY_ENABLED is true; otherwise they do not exist (404).

They sit behind the service-token middleware like every other core route. Nothing here is reachable from /conversation, and errors carry a fixed message, never a filename or content."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from companion_core.document_library.models import (
    MAX_PROJECT,
    MAX_TITLE,
    Document,
    DocumentError,
    Priority,
)
from companion_core.document_library.service import UNSET, DocumentService
from shared.models.document_library import (
    DocumentContentOut,
    DocumentOut,
    DocumentSearchOut,
)
from shared.models.document_worker import WorkerTier
from shared.models.response import Privacy
from shared.protocols.document_library_api import (
    ACCESS_CEILING_HEADER,
    DOCUMENT_LIBRARY_CONFIG,
    DOCUMENT_LIBRARY_DOCUMENT,
    DOCUMENT_LIBRARY_DOCUMENTS,
    DOCUMENT_LIBRARY_LOCATOR,
    DOCUMENT_LIBRARY_READ,
    DOCUMENT_LIBRARY_REPROCESS,
    DOCUMENT_LIBRARY_SEARCH,
)

_CHUNK = 1 << 20


class PatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=MAX_TITLE)
    project_scope: str | None = Field(default=None, max_length=MAX_PROJECT)
    sensitivity: Privacy | None = None
    processing_priority: Priority | None = None


class ReprocessBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: WorkerTier | None = None


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)


def out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id, title=document.title, filename=document.filename, mime_type=document.mime_type, size_bytes=document.size_bytes, source_hash=document.source_hash,
        sensitivity=document.sensitivity, project_scope=document.project_scope, state=document.state.value, processing_priority=document.processing_priority.value, tier=document.tier,
        page_count=document.page_count, error_code=document.error_code, created_at=document.created_at, updated_at=document.updated_at,
    )


def install_document_library_routes(app: FastAPI) -> None:
    def service() -> DocumentService:
        svc = getattr(app.state, "document_library", None)
        if svc is None:
            raise HTTPException(503, "The document library is unavailable")
        return svc

    async def run(call):
        try:
            return await call
        except DocumentError as exc:
            raise HTTPException(exc.status, exc.detail) from None

    @app.get(DOCUMENT_LIBRARY_CONFIG)
    async def config() -> dict:
        return {"enabled": getattr(app.state, "document_library", None) is not None}

    @app.get(DOCUMENT_LIBRARY_DOCUMENTS)
    async def list_documents() -> list[DocumentOut]:
        return [out(d) for d in await service().list_documents()]

    @app.post(DOCUMENT_LIBRARY_DOCUMENTS, status_code=201)
    async def upload(
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form(max_length=MAX_TITLE)] = None,
        sensitivity: Annotated[Privacy | None, Form()] = None,
        project_scope: Annotated[str | None, Form(max_length=MAX_PROJECT)] = None,
        processing_priority: Annotated[Priority, Form()] = Priority.BACKGROUND,
    ) -> DocumentOut:
        async def chunks() -> AsyncIterator[bytes]:
            while block := await file.read(_CHUNK):
                yield block

        document = await run(service().upload(file.filename or "", chunks(), title=title, sensitivity=sensitivity, project_scope=project_scope, priority=processing_priority))
        return out(document)

    @app.get(DOCUMENT_LIBRARY_DOCUMENT)
    async def detail(document_id: str) -> DocumentOut:
        return out(await run(service().get(document_id)))

    @app.patch(DOCUMENT_LIBRARY_DOCUMENT)
    async def patch(document_id: str, body: PatchBody) -> DocumentOut:
        sent = body.model_fields_set
        kwargs = {
            "title": body.title if "title" in sent else UNSET,
            "project_scope": body.project_scope if "project_scope" in sent else UNSET,
            "sensitivity": body.sensitivity if "sensitivity" in sent else UNSET,
            "priority": body.processing_priority if "processing_priority" in sent else UNSET,
        }
        return out(await run(service().update_metadata(document_id, **kwargs)))

    @app.delete(DOCUMENT_LIBRARY_DOCUMENT, status_code=204)
    async def delete(document_id: str) -> None:
        await run(service().delete(document_id))

    def access(request: Request):
        """The caller's access context, from the ceiling the hub established for the authenticated channel (never from the request body or the document). Absent: work-private."""
        from companion_core.semantic.access import access_for_owner

        raw = request.headers.get(ACCESS_CEILING_HEADER)
        try:
            ceiling = Privacy(raw) if raw else Privacy.WORK_PRIVATE
        except ValueError:
            raise HTTPException(400, "Unknown access ceiling") from None
        return access_for_owner(os.environ.get("OWNER_USER_ID", "default-user"), channel_private=ceiling is not Privacy.PUBLIC, allow_sensitive=ceiling is Privacy.SENSITIVE,
                                destinations=frozenset({"local"}))

    @app.post(DOCUMENT_LIBRARY_REPROCESS)
    async def reprocess(document_id: str, body: ReprocessBody | None = None) -> DocumentOut:
        return out(await run(service().reprocess(document_id, (body or ReprocessBody()).tier)))

    @app.get(DOCUMENT_LIBRARY_READ)
    async def read(
        request: Request,
        document_id: str,
        page_range: str | None = Query(default=None, max_length=64, pattern=r"^\d+(-\d+)?(,\d+(-\d+)?)*$"),
        after: str | None = Query(default=None, max_length=256),
        limit: int = Query(default=8000, ge=500, le=30000),
    ) -> DocumentContentOut:
        return await run(service().read(document_id, access(request), page_range=page_range, after=after, limit=limit))

    @app.get(DOCUMENT_LIBRARY_LOCATOR)
    async def locator(request: Request, document_id: str, locator: str = Query(max_length=256), context: int = Query(default=0, ge=0, le=3), limit: int = Query(default=8000, ge=500, le=30000)) -> DocumentContentOut:
        return await run(service().read_locator(document_id, access(request), locator, context=context, limit=limit))

    @app.post(DOCUMENT_LIBRARY_SEARCH)
    async def search(request: Request, document_id: str, body: SearchBody) -> DocumentSearchOut:
        return await run(service().search(document_id, access(request), body.query, limit=body.limit))
