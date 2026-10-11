"""HTTP surface of the document worker. Internal network only, bearer-token protected, and fail-closed without a token."""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse

from document_worker.config import Settings
from document_worker.engine import DoclibEngine, DocumentEngine
from document_worker.service import DocumentService, WorkerError
from document_worker.store import DocumentStore
from shared.models.document_worker import (
    ContentRead,
    DeleteResult,
    DocumentStatus,
    ParseRequest,
    SearchRequest,
    SearchResponse,
    WorkerHealth,
    WorkerTier,
)
from shared.protocols.document_worker_api import (
    WORKER_DOCUMENT,
    WORKER_DOCUMENTS,
    WORKER_HEALTH,
    WORKER_LOCATOR,
    WORKER_PARSE,
    WORKER_READ,
    WORKER_SEARCH,
    WORKER_STATUS,
)

_CHUNK = 1 << 20


def create_app(settings: Settings | None = None, engine: DocumentEngine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine or DoclibEngine(managed_tier=max(settings.tiers, key=("flash", "basic", "standard").index).value)
    service = DocumentService(engine, DocumentStore(settings.work_dir), settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        start = getattr(engine, "start", None)
        if start is not None:
            start()
        yield

    app = FastAPI(title="Reachy document worker", lifespan=lifespan)

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if not settings.token:
            raise HTTPException(503, "document worker token not configured")
        supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not hmac.compare_digest(supplied.encode(), settings.token.encode()):
            raise HTTPException(401, "unauthorized")

    @app.exception_handler(WorkerError)
    async def worker_error(_request, exc: WorkerError):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    @app.get(WORKER_HEALTH, response_model=WorkerHealth)
    def health() -> WorkerHealth:
        return service.health()

    guard = [Depends(require_token)]

    @app.post(WORKER_DOCUMENTS, response_model=DocumentStatus, dependencies=guard)
    def ingest(
        document_id: Annotated[str, Form(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")],
        source_hash: Annotated[str, Form()],
        tier: Annotated[WorkerTier, Form()],
        extension: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ) -> DocumentStatus:
        return service.ingest(document_id, source_hash, tier, extension, iter(lambda: file.file.read(_CHUNK), b""))

    @app.get(WORKER_STATUS, response_model=DocumentStatus, dependencies=guard)
    def status(document_id: str) -> DocumentStatus:
        return service.status(document_id)

    @app.post(WORKER_PARSE, response_model=DocumentStatus, dependencies=guard)
    def parse(document_id: str, body: ParseRequest) -> DocumentStatus:
        return service.parse(document_id, body.tier, body.force)

    @app.get(WORKER_READ, response_model=ContentRead, dependencies=guard)
    def read(
        document_id: str,
        page_range: str | None = Query(default=None, max_length=64),
        after: str | None = Query(default=None, max_length=256),
        limit: int = Query(default=8000, ge=500, le=30000),
    ) -> ContentRead:
        return service.read(document_id, page_range, after, limit)

    @app.get(WORKER_LOCATOR, response_model=ContentRead, dependencies=guard)
    def locator(
        document_id: str,
        locator: str = Query(max_length=256),
        context: int = Query(default=0, ge=0, le=3),
        limit: int = Query(default=8000, ge=500, le=30000),
    ) -> ContentRead:
        return service.read_locator(document_id, locator, context, limit)

    @app.post(WORKER_SEARCH, response_model=SearchResponse, dependencies=guard)
    def search(document_id: str, body: SearchRequest) -> SearchResponse:
        return service.search(document_id, body.query, body.limit)

    @app.delete(WORKER_DOCUMENT, response_model=DeleteResult, dependencies=guard)
    def delete(document_id: str) -> DeleteResult:
        return service.delete(document_id)

    return app
