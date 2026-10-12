"""Reachy's client for the document worker (Phase 50A/50B). The worker is the only door to the document backend: this module holds its URL and token, speaks the shared
contract (shared/protocols/document_worker_api.py) and reduces every failure to a status and a short code, never a message that could carry content or a path."""

from __future__ import annotations

import httpx

from shared.models.document_worker import (
    ContentRead,
    DeleteResult,
    DocumentStatus,
    ExportKind,
    PageInspection,
    SearchResponse,
    WorkerHealth,
    WorkerTier,
)
from shared.protocols.document_worker_api import (
    WORKER_DOCUMENT,
    WORKER_DOCUMENTS,
    WORKER_EXPORT,
    WORKER_HEALTH,
    WORKER_INSPECT_BLOCK_IMAGE,
    WORKER_INSPECT_IMAGE,
    WORKER_INSPECT_PAGE,
    WORKER_LOCATOR,
    WORKER_PARSE,
    WORKER_READ,
    WORKER_SEARCH,
    WORKER_STATUS,
)


class WorkerError(Exception):
    """The worker refused or failed. `status` 0 means it could not be reached at all."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


class DocumentWorkerClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None, timeout: float = 120.0) -> None:
        self._http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def close(self) -> None:
        await self._http.aclose()

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self._http.request(method, path, headers=self._headers, **kwargs)
        except httpx.HTTPError:
            raise WorkerError(0, "worker_unreachable") from None
        if response.status_code >= 400:
            try:
                code = str(response.json().get("error") or "worker_error")
            except ValueError:
                code = "worker_error"
            raise WorkerError(response.status_code, code)
        return response

    async def health(self) -> WorkerHealth:
        return WorkerHealth.model_validate((await self._send("GET", WORKER_HEALTH)).json())

    async def ingest(self, document_id: str, source_hash: str, tier: WorkerTier, extension: str, data: bytes) -> DocumentStatus:
        response = await self._send(
            "POST", WORKER_DOCUMENTS,
            data={"document_id": document_id, "source_hash": source_hash, "tier": tier.value, "extension": extension},
            files={"file": ("source", data, "application/octet-stream")},
        )
        return DocumentStatus.model_validate(response.json())

    async def status(self, document_id: str) -> DocumentStatus:
        return DocumentStatus.model_validate((await self._send("GET", WORKER_STATUS.format(document_id=document_id))).json())

    async def parse(self, document_id: str, tier: WorkerTier, *, force: bool = False) -> DocumentStatus:
        response = await self._send("POST", WORKER_PARSE.format(document_id=document_id), json={"tier": tier.value, "force": force})
        return DocumentStatus.model_validate(response.json())

    async def read(self, document_id: str, *, page_range: str | None = None, after: str | None = None, limit: int = 8000) -> ContentRead:
        params = {k: v for k, v in {"page_range": page_range, "after": after, "limit": limit}.items() if v is not None}
        return ContentRead.model_validate((await self._send("GET", WORKER_READ.format(document_id=document_id), params=params)).json())

    async def read_locator(self, document_id: str, locator: str, *, context: int = 0, limit: int = 8000) -> ContentRead:
        response = await self._send("GET", WORKER_LOCATOR.format(document_id=document_id), params={"locator": locator, "context": context, "limit": limit})
        return ContentRead.model_validate(response.json())

    async def search(self, document_id: str, query: str, *, limit: int = 10) -> SearchResponse:
        response = await self._send("POST", WORKER_SEARCH.format(document_id=document_id), json={"query": query, "limit": limit})
        return SearchResponse.model_validate(response.json())

    async def delete(self, document_id: str) -> DeleteResult:
        return DeleteResult.model_validate((await self._send("DELETE", WORKER_DOCUMENT.format(document_id=document_id))).json())

    # --- extraction inspector -----------------------------------------------------------------------------------

    async def inspect_page(self, document_id: str, page: int) -> PageInspection:
        return PageInspection.model_validate((await self._send("GET", WORKER_INSPECT_PAGE.format(document_id=document_id, page=page))).json())

    async def inspect_image(self, document_id: str, page: int, block: int | None = None, *, image_format: str = "png") -> tuple[bytes, str]:
        path = (WORKER_INSPECT_BLOCK_IMAGE if block else WORKER_INSPECT_IMAGE).format(document_id=document_id, page=page, block=block)
        response = await self._send("GET", path, params={"format": image_format})
        return response.content, response.headers.get("content-type", "application/octet-stream")

    async def export(self, document_id: str, kind: ExportKind) -> tuple[bytes, str, str]:
        response = await self._send("GET", WORKER_EXPORT.format(document_id=document_id), params={"format": kind.value})
        return response.content, response.headers.get("content-type", "application/octet-stream"), response.headers.get("x-export-extension", "bin")
