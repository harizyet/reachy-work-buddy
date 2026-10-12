"""Document records. The in-memory twin has the same guarantees as the PostgreSQL store (postgres_store.py)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Protocol

from companion_core.document_library.models import (
    SYNCABLE,
    UPDATABLE_FIELDS,
    Document,
    DocumentOutput,
    DocumentState,
    OutputStatus,
)


class DocumentStore(Protocol):
    async def add(self, document: Document) -> Document: ...
    async def get(self, document_id: str) -> Document | None: ...
    async def list(self) -> list[Document]: ...
    async def update(self, document_id: str, now: datetime, **fields) -> Document | None: ...
    async def begin_delete(self, document_id: str, now: datetime) -> Document | None: ...
    async def count_by_hash(self, source_hash: str) -> int: ...
    async def remove(self, document_id: str) -> bool: ...
    async def deleting(self) -> list[Document]: ...
    async def pending_sync(self) -> list[Document]: ...
    async def begin_output(self, output: DocumentOutput) -> tuple[DocumentOutput, bool]: ...
    async def get_output(self, output_id: str) -> DocumentOutput | None: ...
    async def list_outputs(self, document_id: str) -> list[DocumentOutput]: ...
    async def finish_output(self, output_id: str, now: datetime, **fields) -> DocumentOutput | None: ...
    async def supersede_outputs(self, document_id: str, now: datetime, *, kind: str | None = None, style: str | None = None) -> int: ...
    async def delete_outputs(self, document_id: str) -> int: ...
    async def fail_running_outputs(self, now: datetime) -> int: ...


class InMemoryDocumentStore:
    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}
        self._outputs: dict[str, DocumentOutput] = {}

    async def add(self, document: Document) -> Document:
        self._docs[document.id] = document
        return document

    async def get(self, document_id: str) -> Document | None:
        return self._docs.get(document_id)

    async def list(self) -> list[Document]:
        return sorted(self._docs.values(), key=lambda d: d.created_at, reverse=True)

    async def update(self, document_id: str, now: datetime, **fields) -> Document | None:
        """Change fields of a document that is not being deleted (a document in DELETING never comes back)."""
        unknown = set(fields) - UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"not an updatable field: {sorted(unknown)}")  # the same refusal as the PostgreSQL store, so a test cannot pass on a field production rejects
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

    async def pending_sync(self) -> list[Document]:
        return sorted((d for d in self._docs.values() if d.state in SYNCABLE), key=lambda d: d.created_at)

    # --- derived outputs -------------------------------------------------------------------------------------

    def _active(self, document_id: str, kind: str, style: str) -> DocumentOutput | None:
        return next((o for o in self._outputs.values() if (o.document_id, o.kind, o.style) == (document_id, kind, style) and not o.stale and o.status in (OutputStatus.RUNNING, OutputStatus.READY)), None)

    async def begin_output(self, output: DocumentOutput) -> tuple[DocumentOutput, bool]:
        """Start an output unless a current (not stale) running or ready one of the same kind and style exists, which is returned instead."""
        existing = self._active(output.document_id, output.kind, output.style)
        if existing is not None:
            return existing, False
        self._outputs[output.id] = output
        return output, True

    async def get_output(self, output_id: str) -> DocumentOutput | None:
        return self._outputs.get(output_id)

    async def list_outputs(self, document_id: str) -> list[DocumentOutput]:
        return sorted((o for o in self._outputs.values() if o.document_id == document_id), key=lambda o: o.created_at, reverse=True)

    async def finish_output(self, output_id: str, now: datetime, **fields) -> DocumentOutput | None:
        current = self._outputs.get(output_id)
        if current is None:
            return None
        self._outputs[output_id] = updated = replace(current, updated_at=now, **fields)
        return updated

    async def supersede_outputs(self, document_id: str, now: datetime, *, kind: str | None = None, style: str | None = None) -> int:
        """Mark the document's current outputs stale (all of them, or one kind and style). Their text stays readable as out of date until the document is deleted."""
        count = 0
        for key, output in list(self._outputs.items()):
            if output.document_id == document_id and not output.stale and (kind is None or output.kind == kind) and (style is None or output.style == style):
                self._outputs[key] = replace(output, stale=True, updated_at=now)
                count += 1
        return count

    async def delete_outputs(self, document_id: str) -> int:
        gone = [key for key, o in self._outputs.items() if o.document_id == document_id]
        for key in gone:
            del self._outputs[key]
        return len(gone)

    async def fail_running_outputs(self, now: datetime) -> int:
        """At startup: an output left running by a stopped process will never finish."""
        count = 0
        for key, output in list(self._outputs.items()):
            if output.status is OutputStatus.RUNNING:
                self._outputs[key] = replace(output, status=OutputStatus.FAILED, error_code="interrupted", updated_at=now)
                count += 1
        return count

    async def close(self) -> None:
        return None
