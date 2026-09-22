"""companion-core: reasoning/tools/memory service.

Phase 4: minimal service proving companion-core -> reachy-hub ->
reachy-embodiment end to end. The `/debug/*` routes are a stand-in for what
will eventually be an agent tool call — not the tool-calling framework
itself.

Phase 5: POST /conversation is the real, stable contract reachy-hub calls
per turn (ADR 0002) — companion-core receives only a session_id,
conversation_id, channel label, and text, never "this came from Telegram"
as anything but an opaque string. The reasoning inside is a placeholder
(echoes turn count) until Phase 10+ replaces it with a real agent.

Phase 9: the response now carries real (if simplistic) `Privacy`/`Urgency`
metadata (privacy_classifier.py) — companion-core *proposes* this per
docs/plan.md §4 ("the LLM may propose metadata"); reachy-hub's response
router (Phase 9, ADR 0006) has final, enforced authority over what actually
happens with it.

Phase 10: calendar, per docs/plan.md's Phase 10 row ("Read-only
next/list/free-busy first; later writes behind confirmation") — see
calendar/. companion-core owns a real database connection for the first
time (previously entirely stateless beyond the in-memory conversation
transcript); no external calendar credential was available, so the
concrete `CalendarStore` is a local Postgres-backed one (calendar/
postgres_store.py), matching the graceful-degradation-without-credentials
pattern used for Telegram/TTS. `is_next_event_query` (calendar_intent.py)
is a placeholder keyword matcher (same honesty-about-scope as
privacy_classifier.py) that answers "what's next" using real stored
calendar data — Phase 10's exit criterion is that the *answer* is real,
not that the question-understanding is sophisticated.

Phase 11: tasks/notes/reminders, per docs/plan.md's Phase 11 row ("Capture,
list, complete and search basic work items") — see tasks/. Unlike
calendar, capturing a task *is* the agent action this phase is about
("Agent can record... explicit follow-ups"): `POST /conversation`
recognizes capture/list/complete/search phrasings (task_intent.py, same
placeholder-matcher honesty as calendar_intent.py) and calls `TaskStore`
directly — no separate admin/confirmation gate, since recording a task is
low-stakes and easily undoable (docs/plan.md §9's permission tiers), unlike
a calendar write (still admin-only, ADR 0010) or an email send (Phase 14).

Phase 12: work memory, per docs/plan.md's Phase 12 row ("Profile, working
and episodic memory with provenance, sensitivity and expiry") — see
memory/. `MemoryRecord` (shared/models/memory.py) has existed as a
forward-looking data contract since Phase 0; this phase is the first real
implementation against it. `POST /conversation` recognizes "remember that
X" (memory_intent.py, same placeholder-matcher pattern as calendar/task
intent) and stores it via `MemoryStore.add_memory` directly — memory
capture is the same kind of low-stakes, no-confirmation-needed agent action
task capture (Phase 11) is, not calendar's read-only-to-the-agent design.
"Do you remember X" recalls by content search against `MemoryStore` —
never against `conversation.py`'s per-session transcript — which is the
literal mechanism behind the exit criterion, "Stored work fact can be
recalled later without transcript dumping."
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from companion_core import memory_intent
from companion_core.calendar.models import CalendarEvent
from companion_core.calendar.postgres_store import PostgresCalendarStore
from companion_core.calendar.reminders import due_reminders
from companion_core.calendar.store import CalendarStore
from companion_core.calendar_intent import format_next_event_reply, is_next_event_query
from companion_core.conversation import ConversationStore
from companion_core.hub_client import HubClient
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.memory.store import MemoryStore
from companion_core.privacy_classifier import classify_privacy
from companion_core.task_intent import (
    format_capture_reply,
    format_complete_reply,
    format_list_reply,
    format_search_reply,
    is_list_query,
    match_capture,
    match_complete,
    match_search,
)
from companion_core.tasks.models import Task, TaskStatus
from companion_core.tasks.postgres_store import PostgresTaskStore
from companion_core.tasks.store import TaskStore
from shared.models.memory import MemoryRecord, MemoryType
from shared.models.response import Privacy, Urgency


class ConversationTurnRequest(BaseModel):
    session_id: str
    conversation_id: str
    channel: str
    text: str


class ConversationTurnResponse(BaseModel):
    reply: str
    turn_count: int
    privacy: Privacy


class ReminderPayload(BaseModel):
    event_id: str
    text: str
    privacy: Privacy
    urgency: Urgency


class CreateTaskRequest(BaseModel):
    text: str


class CreateMemoryRequest(BaseModel):
    content: str
    type: MemoryType = MemoryType.WORKING
    project_scope: str | None = None
    confidence: float = 1.0
    sensitivity: Privacy | None = None
    expires_at: datetime | None = None


def create_app(
    *,
    hub_base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    calendar_store: CalendarStore | None = None,
    task_store: TaskStore | None = None,
    memory_store: MemoryStore | None = None,
    database_url: str | None = None,
) -> FastAPI:
    hub_base_url = hub_base_url or os.environ.get("REACHY_HUB_URL", "http://reachy-hub:8000")
    conversation_store = ConversationStore()
    owns_calendar_store = calendar_store is None
    owns_task_store = task_store is None
    owns_memory_store = memory_store is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.hub_client = HubClient(hub_base_url, transport=transport)
        if owns_calendar_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.calendar_store = await PostgresCalendarStore.connect(dsn)
        if owns_task_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.task_store = await PostgresTaskStore.connect(dsn)
        if owns_memory_store:
            dsn = database_url or os.environ["DATABASE_URL"]
            app.state.memory_store = await PostgresMemoryStore.connect(dsn)
        try:
            yield
        finally:
            await app.state.hub_client.aclose()
            if owns_calendar_store:
                await app.state.calendar_store.close()
            if owns_task_store:
                await app.state.task_store.close()
            if owns_memory_store:
                await app.state.memory_store.close()

    app = FastAPI(title="companion-core", lifespan=lifespan)
    app.state.conversation_store = conversation_store
    if not owns_calendar_store:
        app.state.calendar_store = calendar_store
    if not owns_task_store:
        app.state.task_store = task_store
    if not owns_memory_store:
        app.state.memory_store = memory_store

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/conversation")
    async def conversation_turn(turn: ConversationTurnRequest) -> ConversationTurnResponse:
        history = conversation_store.append(turn.session_id, turn.channel, turn.text)

        capture_text = match_capture(turn.text)
        complete_query = match_complete(turn.text)
        search_query = match_search(turn.text)
        memory_capture_text = memory_intent.match_capture(turn.text)
        memory_recall_query = memory_intent.match_recall(turn.text)

        if is_next_event_query(turn.text):
            event = await app.state.calendar_store.next_event(datetime.now(UTC))
            reply = format_next_event_reply(event)
            # Calendar content is inherently work-private (docs/plan.md §4's
            # routing table) regardless of whether the query text itself
            # happens to contain a privacy keyword — we know for certain
            # this reply reveals schedule details, so this isn't inferred
            # from turn.text the way the generic placeholder reply is.
            privacy = Privacy.WORK_PRIVATE
        elif capture_text:
            task = await app.state.task_store.add_task(capture_text)
            reply = format_capture_reply(task)
            privacy = classify_privacy(turn.text)
        elif complete_query:
            open_tasks = await app.state.task_store.list_tasks(TaskStatus.OPEN)
            matched = next((t for t in open_tasks if complete_query.lower() in t.text.lower()), None)
            completed = await app.state.task_store.complete_task(matched.id) if matched else None
            reply = format_complete_reply(completed, complete_query)
            privacy = classify_privacy(turn.text)
        elif search_query:
            found = await app.state.task_store.search_tasks(search_query)
            reply = format_search_reply(found, search_query)
            privacy = classify_privacy(turn.text)
        elif is_list_query(turn.text):
            open_tasks = await app.state.task_store.list_tasks(TaskStatus.OPEN)
            reply = format_list_reply(open_tasks)
            privacy = classify_privacy(turn.text)
        elif memory_capture_text:
            record = await app.state.memory_store.add_memory(
                content=memory_capture_text,
                source="conversation",
                sensitivity=classify_privacy(memory_capture_text),
            )
            reply = memory_intent.format_capture_reply(record)
            privacy = record.sensitivity
        elif memory_recall_query:
            # Deliberately queries MemoryStore only — never conversation_store
            # — this is the exit criterion's "without transcript dumping" as
            # an actual code-level guarantee, not just a claim.
            found = await app.state.memory_store.recall(memory_recall_query)
            reply = memory_intent.format_recall_reply(found, memory_recall_query)
            privacy = memory_intent.most_restrictive_privacy(found, default=classify_privacy(turn.text))
        else:
            reply = f"(turn {len(history)} via {turn.channel}) heard: {turn.text}"
            privacy = classify_privacy(turn.text)

        return ConversationTurnResponse(reply=reply, turn_count=len(history), privacy=privacy)

    @app.post("/calendar/events")
    async def add_calendar_event(event: CalendarEvent) -> CalendarEvent:
        """Operator/setup API, not an agent tool: with no external calendar
        sync in this V0.1 default, this is how events get into the store at
        all. The agent's own access is read-only (next_event et al.)."""
        return await app.state.calendar_store.add_event(event)

    @app.get("/calendar/events")
    async def list_calendar_events(start: datetime, end: datetime) -> list[CalendarEvent]:
        return await app.state.calendar_store.list_events(start, end)

    @app.get("/calendar/next")
    async def next_calendar_event() -> CalendarEvent | None:
        return await app.state.calendar_store.next_event(datetime.now(UTC))

    @app.get("/calendar/free-busy")
    async def free_busy(start: datetime, end: datetime) -> list[dict[str, datetime]]:
        # Free/busy intentionally reveals only time blocks, not what's in
        # them — a different (narrower) privacy surface than /calendar/events.
        events = await app.state.calendar_store.list_events(start, end)
        return [{"start": event.start, "end": event.end} for event in events]

    @app.get("/calendar/reminders/due")
    async def reminders_due(within_minutes: int = 15) -> list[ReminderPayload]:
        events = await due_reminders(app.state.calendar_store, datetime.now(UTC), within_minutes)
        return [
            ReminderPayload(
                event_id=event.id,
                text=f"Reminder: '{event.title}' starts at {event.start.strftime('%H:%M')}.",
                privacy=Privacy.WORK_PRIVATE,
                urgency=Urgency.URGENT,
            )
            for event in events
        ]

    @app.post("/memories")
    async def create_memory(request: CreateMemoryRequest) -> MemoryRecord:
        """Direct/API capture, alongside the conversational path in
        /conversation — e.g. to seed profile facts up front rather than
        waiting for them to come up naturally in conversation."""
        return await app.state.memory_store.add_memory(
            content=request.content,
            source="api",
            type=request.type,
            project_scope=request.project_scope,
            confidence=request.confidence,
            sensitivity=request.sensitivity or classify_privacy(request.content),
            expires_at=request.expires_at,
        )

    @app.get("/memories")
    async def list_memories(type: MemoryType | None = None) -> list[MemoryRecord]:
        return await app.state.memory_store.list_memories(type)

    @app.get("/memories/recall")
    async def recall_memories(q: str, type: MemoryType | None = None) -> list[MemoryRecord]:
        return await app.state.memory_store.recall(q, type=type)

    @app.delete("/memories/{memory_id}")
    async def forget_memory(memory_id: str) -> dict[str, bool]:
        forgotten = await app.state.memory_store.forget(memory_id)
        if not forgotten:
            raise HTTPException(status_code=404, detail=f"no memory '{memory_id}'")
        return {"forgotten": True}

    @app.get("/tasks")
    async def list_tasks(status: TaskStatus | None = None) -> list[Task]:
        return await app.state.task_store.list_tasks(status)

    @app.post("/tasks")
    async def create_task(request: CreateTaskRequest) -> Task:
        """Direct/API capture, alongside the conversational path in
        /conversation — e.g. for a future web UI that isn't going through a
        chat turn at all."""
        return await app.state.task_store.add_task(request.text)

    @app.post("/tasks/{task_id}/complete")
    async def complete_task_by_id(task_id: str) -> Task:
        task = await app.state.task_store.complete_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"no task '{task_id}'")
        return task

    @app.get("/tasks/search")
    async def search_tasks_endpoint(q: str) -> list[Task]:
        return await app.state.task_store.search_tasks(q)

    @app.get("/debug/robots/{robot_id}/state")
    async def debug_robot_state(robot_id: str) -> dict:
        try:
            return await app.state.hub_client.get_robot_state(robot_id)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"reachy-hub unreachable: {exc}") from exc

    @app.post("/debug/robots/{robot_id}/behaviour/{name}")
    async def debug_trigger_behaviour(robot_id: str, name: str) -> dict:
        try:
            return await app.state.hub_client.trigger_behaviour(robot_id, name)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"reachy-hub unreachable: {exc}") from exc

    return app
