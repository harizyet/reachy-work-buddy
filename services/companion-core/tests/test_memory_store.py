"""No pytest-asyncio/anyio-plugin is installed anywhere else in this
codebase — wrapping each test body in asyncio.run keeps these genuinely
sync test functions (same pattern as test_calendar_store.py/test_task_store.py)."""

import asyncio
from datetime import UTC, datetime, timedelta

from companion_core.memory.store import InMemoryMemoryStore

from shared.models.memory import MemoryType
from shared.models.response import Privacy


def test_add_and_recall_memory() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        await store.add_memory(content="my manager is Alice", source="conversation")

        found = await store.recall("Alice")
        assert len(found) == 1
        assert found[0].content == "my manager is Alice"
        assert found[0].last_accessed is not None  # recall touches provenance

    asyncio.run(run())


def test_recall_is_case_insensitive_substring_match() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        await store.add_memory(content="Project codename is Falcon", source="conversation")

        assert len(await store.recall("falcon")) == 1
        assert len(await store.recall("nonexistent")) == 0

    asyncio.run(run())


def test_recall_filters_by_type() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        await store.add_memory(content="likes coffee", source="conversation", type=MemoryType.PROFILE)
        await store.add_memory(content="likes coffee shops", source="conversation", type=MemoryType.WORKING)

        profile_only = await store.recall("coffee", type=MemoryType.PROFILE)
        assert len(profile_only) == 1
        assert profile_only[0].type == MemoryType.PROFILE

    asyncio.run(run())


def test_list_memories_returns_everything_unfiltered() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        await store.add_memory(content="fact one", source="conversation")
        await store.add_memory(content="fact two", source="conversation")

        assert len(await store.list_memories()) == 2

    asyncio.run(run())


def test_expired_memory_is_never_recalled_or_listed() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        record = await store.add_memory(
            content="temporary fact",
            source="conversation",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        assert await store.recall("temporary") == []
        assert await store.list_memories() == []
        assert await store.get(record.id) is None

    asyncio.run(run())


def test_unexpired_memory_with_future_expiry_is_still_recalled() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        await store.add_memory(
            content="fact that expires later",
            source="conversation",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )

        assert len(await store.recall("expires later")) == 1

    asyncio.run(run())


def test_forget_is_a_soft_delete() -> None:
    """docs/adr/0011: forgetting hides a record from recall/list/get, but
    never removes it — "any action performed should always be able to be
    undone" — so restore() can always bring it back."""

    async def run() -> None:
        store = InMemoryMemoryStore()
        record = await store.add_memory(content="forget me", source="conversation")

        forgotten = await store.forget(record.id)
        assert forgotten is not None
        assert forgotten.forgotten_at is not None
        assert await store.get(record.id) is None
        assert await store.recall("forget me") == []
        assert await store.list_memories() == []
        assert await store.forget(record.id) is None  # already forgotten

    asyncio.run(run())


def test_restore_undoes_a_forget() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        record = await store.add_memory(content="forget me", source="conversation")
        await store.forget(record.id)

        restored = await store.restore(record.id)
        assert restored is not None
        assert restored.forgotten_at is None
        assert await store.get(record.id) is not None
        assert len(await store.recall("forget me")) == 1
        assert await store.restore(record.id) is None  # already restored, not forgotten

    asyncio.run(run())


def test_restore_unknown_memory_returns_none() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        assert await store.restore("nonexistent") is None

    asyncio.run(run())


def test_find_forgotten_matches_content_substring() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        record = await store.add_memory(content="my manager is Alice", source="conversation")
        await store.forget(record.id)
        await store.add_memory(content="unrelated fact", source="conversation")  # never forgotten

        found = await store.find_forgotten("alice")
        assert len(found) == 1
        assert found[0].id == record.id

        assert await store.find_forgotten("unrelated") == []  # not forgotten, so not found here

    asyncio.run(run())


def test_sensitivity_defaults_to_work_private() -> None:
    async def run() -> None:
        store = InMemoryMemoryStore()
        record = await store.add_memory(content="a fact", source="conversation")
        assert record.sensitivity == Privacy.WORK_PRIVATE

    asyncio.run(run())
