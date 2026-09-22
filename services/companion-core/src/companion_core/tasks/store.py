"""Task storage. Unlike calendar (ADR 0010, read-only to the agent),
capturing a task *is* the agent action Phase 11's exit criterion is about —
"Agent can record and later retrieve explicit follow-ups" — so add_task is
called directly from the conversation flow (task_intent.py), not gated
behind a separate admin/confirmation step. Recording a task is low-stakes
and easily undoable, unlike an email send (Phase 14) or a calendar write —
see docs/plan.md §9's permission tiers.

Single task list, not scoped per user — same precedent as Telegram/calendar
(this is a personal assistant, not multi-tenant).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from companion_core.tasks.models import Task, TaskStatus


class TaskStore(Protocol):
    async def add_task(self, text: str) -> Task: ...
    async def list_tasks(self, status: TaskStatus | None = None) -> list[Task]: ...
    async def complete_task(self, task_id: str) -> Task | None: ...
    async def search_tasks(self, query: str) -> list[Task]: ...


class InMemoryTaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    async def add_task(self, text: str) -> Task:
        task = Task(text=text)
        self._tasks[task.id] = task
        return task

    async def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at)

    async def complete_task(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
        return task

    async def search_tasks(self, query: str) -> list[Task]:
        lowered = query.lower()
        matches = [t for t in self._tasks.values() if lowered in t.text.lower()]
        return sorted(matches, key=lambda t: t.created_at)
