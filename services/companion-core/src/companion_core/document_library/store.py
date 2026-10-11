"""Document records. The in-memory twin has the same guarantees as the PostgreSQL store (postgres_store.py)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Protocol

from companion_core.document_library.models import Document, DocumentState


class DocumentStore(Protocol):
    async def add(self, document: Document) -> Document: ...
    async def get(self, document_id: str) -> Document | None: ...
    async def list(self) -> list[Document]: ...
    async def update(self, document_id: str, now: datetime, **fields) -> Document | None: ...
    async def begin_delete(self, document_id: str, now: datetime) -> Document | None: ...
    async def count_by_hash(self, source_hash: str) -> int: ...
    async def remove(self, document_id: str) -> bool: ...
    async def deleting(self) -> list[Document]: ...


class InMemoryDocumentStore:
    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}

    async def add(self, document: Document) -> Document:
        self._docs[document.id] = document
        return document

    async def get(self, document_id: str) -> Document | None:
        return self._docs.get(document_id)

    async def list(self) -> list[Document]:
        return sorted(self._docs.values(), key=lambda d: d.created_at, reverse=True)

    async def update(self, document_id: str, now: datetime, **fields) -> Document | None:
        """Change fields of a document that is not being deleted (a document in DELETING never comes back)."""
        current = self._docs.get(document_id)
        if current is None or current.state is DocumentState.DELETING:
            return None
        self._docs[document_id] = updated = replace(current, updated_at=now, **fields)
        return updated

    async def begin_delete(self, document_id: str, now: datetime) -> Document | None:
        current = self._docs.get(document_id)
        if current is None:
            return None
        if current.state is not DocumentState.DELETING:
            self._docs[document_id] = current = replace(current, state=DocumentState.DELETING, updated_at=now)
        return current

    async def count_by_hash(self, source_hash: str) -> int:
        return sum(1 for d in self._docs.values() if d.source_hash == source_hash)

    async def remove(self, document_id: str) -> bool:
        return self._docs.pop(document_id, None) is not None

    async def deleting(self) -> list[Document]:
        return [d for d in self._docs.values() if d.state is DocumentState.DELETING]

    async def close(self) -> None:
        return None
