"""Same asyncio.run wrapper pattern as the other *_store tests (no
pytest-asyncio/anyio plugin installed)."""

import asyncio

from companion_core.email.models import DraftStatus
from companion_core.email.store import InMemoryEmailStore


def test_add_and_list_received() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        await store.add_received(sender="boss@example.com", subject="Q3 report", body="See attached.")

        received = await store.list_received()
        assert len(received) == 1
        assert received[0].sender == "boss@example.com"

    asyncio.run(run())


def test_create_draft_starts_in_draft_status() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello there")
        assert draft.status == DraftStatus.DRAFT
        assert draft.approved_at is None
        assert draft.sent_at is None

    asyncio.run(run())


def test_approve_draft_moves_draft_to_approved() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")

        approved = await store.approve_draft(draft.id)
        assert approved is not None
        assert approved.status == DraftStatus.APPROVED
        assert approved.approved_at is not None

    asyncio.run(run())


def test_approve_draft_twice_fails_the_second_time() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)

        assert await store.approve_draft(draft.id) is None  # already approved, not DRAFT anymore

    asyncio.run(run())


def test_approve_unknown_draft_returns_none() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        assert await store.approve_draft("nonexistent") is None

    asyncio.run(run())


def test_mark_sent() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)

        sent = await store.mark_sent(draft.id)
        assert sent is not None
        assert sent.status == DraftStatus.SENT
        assert sent.sent_at is not None

    asyncio.run(run())


def test_list_drafts_filters_by_status() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        d1 = await store.create_draft(to="a@example.com", subject="One", body="body")
        await store.create_draft(to="b@example.com", subject="Two", body="body")
        await store.approve_draft(d1.id)

        approved_only = await store.list_drafts(DraftStatus.APPROVED)
        assert len(approved_only) == 1
        assert approved_only[0].id == d1.id

        assert len(await store.list_drafts()) == 2

    asyncio.run(run())


def test_get_draft_returns_none_for_unknown_id() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        assert await store.get_draft("nonexistent") is None

    asyncio.run(run())
