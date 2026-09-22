"""DocumentStore: ingestion + provenance-aware retrieval for RAG (Phase
13). `embed_fn` is injectable on both implementations specifically so unit
tests don't have to load the real sentence-transformers model (slow, a
real ~90MB download) — tests inject a small deterministic fake embedder
and get fast, repeatable results; one `slow`-marked test exercises the
real model end to end. Same "unit test the step function with controlled
inputs, keep one real test as sanity check" split AGENTS.md documents for
the presence/heartbeat loops.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Protocol

from companion_core.rag.chunking import split_into_chunks
from companion_core.rag.embeddings import embed
from shared.models.rag import DocumentChunk, RetrievedChunk

EmbedFn = Callable[[list[str]], list[list[float]]]


class DocumentStore(Protocol):
    async def ingest_document(self, *, title: str, content: str, source: str) -> list[DocumentChunk]: ...

    async def search(self, query: str, *, top_k: int = 3) -> list[RetrievedChunk]: ...

    async def list_documents(self) -> list[str]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryDocumentStore:
    def __init__(self, *, embed_fn: EmbedFn = embed) -> None:
        self._embed_fn = embed_fn
        self._chunks: dict[str, DocumentChunk] = {}
        self._embeddings: dict[str, list[float]] = {}

    async def ingest_document(self, *, title: str, content: str, source: str) -> list[DocumentChunk]:
        document_id = str(uuid.uuid4())
        pieces = split_into_chunks(content)
        vectors = self._embed_fn([text for _, text in pieces])
        chunks: list[DocumentChunk] = []
        for index, ((section, text), vector) in enumerate(zip(pieces, vectors, strict=True)):
            chunk = DocumentChunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                document_title=title,
                section=section,
                content=text,
                source=source,
                chunk_index=index,
            )
            self._chunks[chunk.id] = chunk
            self._embeddings[chunk.id] = vector
            chunks.append(chunk)
        return chunks

    async def search(self, query: str, *, top_k: int = 3) -> list[RetrievedChunk]:
        if not self._chunks:
            return []
        (query_vector,) = self._embed_fn([query])
        scored = [
            RetrievedChunk(chunk=chunk, score=_cosine(query_vector, self._embeddings[chunk_id]))
            for chunk_id, chunk in self._chunks.items()
        ]
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    async def list_documents(self) -> list[str]:
        return sorted({chunk.document_title for chunk in self._chunks.values()})
