"""No pytest-asyncio/anyio-plugin is installed anywhere else in this
codebase — wrapping each test body in asyncio.run keeps these genuinely
sync test functions (see test_calendar_store.py for the same pattern)."""

import asyncio

from companion_core.tasks.models import TaskStatus
from companion_core.tasks.store import InMemoryTaskStore


def test_add_and_list_tasks() -> None:
    async def run() -> None:
        store = InMemoryTaskStore()
        await store.add_task("buy milk")
        await store.add_task("call dentist")

        tasks = await store.list_tasks()
        assert [t.text for t in tasks] == ["buy milk", "call dentist"]
        assert all(t.status == TaskStatus.OPEN for t in tasks)

    asyncio.run(run())


def test_complete_task_marks_done_and_sets_completed_at() -> None:
    async def run() -> None:
        store = InMemoryTaskStore()
        task = await store.add_task("buy milk")

        completed = await store.complete_task(task.id)
        assert completed.status == TaskStatus.DONE
        assert completed.completed_at is not None

        open_tasks = await store.list_tasks(TaskStatus.OPEN)
        assert open_tasks == []

    asyncio.run(run())


def test_complete_unknown_task_returns_none() -> None:
    async def run() -> None:
        store = InMemoryTaskStore()
        assert await store.complete_task("nope") is None

    asyncio.run(run())


def test_list_tasks_filters_by_status() -> None:
    async def run() -> None:
        store = InMemoryTaskStore()
        open_task = await store.add_task("open one")
        done_task = await store.add_task("done one")
        await store.complete_task(done_task.id)

        open_only = await store.list_tasks(TaskStatus.OPEN)
        done_only = await store.list_tasks(TaskStatus.DONE)
        assert [t.id for t in open_only] == [open_task.id]
        assert [t.id for t in done_only] == [done_task.id]

    asyncio.run(run())


def test_search_tasks_is_case_insensitive_substring_match() -> None:
    async def run() -> None:
        store = InMemoryTaskStore()
        await store.add_task("Buy Milk")
        await store.add_task("call dentist")

        results = await store.search_tasks("milk")
        assert [t.text for t in results] == ["Buy Milk"]

    asyncio.run(run())
