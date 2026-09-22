"""Unit tests for InMemoryDocumentStore, using a deterministic fake
embedder (not the real sentence-transformers model — that's exercised
separately by a `slow`-marked test) so these stay fast and repeatable.
Same asyncio.run wrapper pattern as test_calendar_store.py/test_task_store.py
/test_memory_store.py (no pytest-asyncio/anyio plugin installed).
"""

import asyncio
import hashlib

import pytest
from companion_core.rag.embeddings import EMBEDDING_DIM, embed
from companion_core.rag.store import InMemoryDocumentStore

_FAKE_EMBED_DIM = 16


def _fake_embed(texts: list[str]) -> list[list[float]]:
    vectors = []
    for text in texts:
        vector = [0.0] * _FAKE_EMBED_DIM
        for word in text.lower().split():
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % _FAKE_EMBED_DIM
            vector[bucket] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        vectors.append([v / norm for v in vector] if norm else vector)
    return vectors


def test_ingest_returns_one_chunk_per_paragraph() -> None:
    async def run() -> None:
        store = InMemoryDocumentStore(embed_fn=_fake_embed)
        chunks = await store.ingest_document(
            title="Onboarding Guide",
            content="# Getting started\nwelcome aboard\n\n# Benefits\nsee HR for details",
            source="onboarding.md",
        )
        assert len(chunks) == 2
        assert chunks[0].section == "Getting started"
        assert chunks[1].section == "Benefits"
        assert all(c.document_title == "Onboarding Guide" for c in chunks)
        assert all(c.source == "onboarding.md" for c in chunks)

    asyncio.run(run())


def test_search_returns_the_most_relevant_chunk_first() -> None:
    async def run() -> None:
        store = InMemoryDocumentStore(embed_fn=_fake_embed)
        await store.ingest_document(
            title="Vacation Policy", content="# Requesting time off\nsubmit a request in Workday", source="hr.md"
        )
        await store.ingest_document(
            title="Expense Policy", content="# Filing expenses\nsubmit receipts within 30 days", source="finance.md"
        )

        results = await store.search("how do I request time off")
        assert results
        assert results[0].chunk.document_title == "Vacation Policy"
        assert results[0].score > 0

    asyncio.run(run())


def test_search_on_empty_store_returns_nothing() -> None:
    async def run() -> None:
        store = InMemoryDocumentStore(embed_fn=_fake_embed)
        assert await store.search("anything") == []

    asyncio.run(run())


def test_search_respects_top_k() -> None:
    async def run() -> None:
        store = InMemoryDocumentStore(embed_fn=_fake_embed)
        # Separate headings force separate chunks — same-section paragraphs
        # get packed together by chunking.py, so plain blank-line-separated
        # text here would collapse into a single chunk instead of three.
        await store.ingest_document(title="Doc", content="# A\nalpha\n\n# B\nbeta\n\n# C\ngamma", source="doc.md")

        results = await store.search("alpha beta gamma", top_k=2)
        assert len(results) == 2

    asyncio.run(run())


def test_list_documents_returns_distinct_titles() -> None:
    async def run() -> None:
        store = InMemoryDocumentStore(embed_fn=_fake_embed)
        await store.ingest_document(title="Doc A", content="one\n\ntwo", source="a.md")
        await store.ingest_document(title="Doc A", content="three", source="a.md")
        await store.ingest_document(title="Doc B", content="four", source="b.md")

        assert await store.list_documents() == ["Doc A", "Doc B"]

    asyncio.run(run())


@pytest.mark.slow
def test_real_embedding_model_produces_correctly_sized_vectors() -> None:
    vectors = embed(["hello world", "a second sentence"])
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vectors)


@pytest.mark.slow
def test_real_embedding_model_end_to_end_search() -> None:
    async def run() -> None:
        store = InMemoryDocumentStore()  # real embed_fn default
        await store.ingest_document(
            title="Vacation Policy", content="# Requesting time off\nsubmit a request in Workday", source="hr.md"
        )
        await store.ingest_document(
            title="Expense Policy", content="# Filing expenses\nsubmit receipts within 30 days", source="finance.md"
        )

        results = await store.search("how do I take time off work")
        assert results[0].chunk.document_title == "Vacation Policy"

    asyncio.run(run())
