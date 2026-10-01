"""29.1: session/event store. In-memory only for now — Postgres durability
across a process restart is 29.27's reconciliation stage, not this one; see
docs/phase-29.md's implementation sequence. A Postgres-backed store can be
added later behind the same Protocol, same precedent as companion-core's
tasks/calendar/meetings stores.
"""

from __future__ import annotations

from typing import Protocol

from shared.models.coding_agent import (
    CodingAgentEvent,
    CodingAgentSession,
    CodingProject,
)


class CodingAgentStore(Protocol):
    async def add_project(self, project: CodingProject) -> CodingProject: ...
    async def get_project(self, project_id: str) -> CodingProject | None: ...
    async def list_projects(self) -> list[CodingProject]: ...

    async def add_session(self, session: CodingAgentSession) -> CodingAgentSession: ...
    async def get_session(self, session_id: str) -> CodingAgentSession | None: ...
    async def list_sessions(self) -> list[CodingAgentSession]: ...
    async def update_session(self, session: CodingAgentSession) -> CodingAgentSession: ...

    async def add_event(self, event: CodingAgentEvent) -> CodingAgentEvent: ...
    async def list_events(self, session_id: str) -> list[CodingAgentEvent]: ...


class InMemoryCodingAgentStore:
    def __init__(self) -> None:
        self._projects: dict[str, CodingProject] = {}
        self._sessions: dict[str, CodingAgentSession] = {}
        self._events: dict[str, list[CodingAgentEvent]] = {}

    async def add_project(self, project: CodingProject) -> CodingProject:
        self._projects[project.id] = project
        return project

    async def get_project(self, project_id: str) -> CodingProject | None:
        return self._projects.get(project_id)

    async def list_projects(self) -> list[CodingProject]:
        return sorted(self._projects.values(), key=lambda p: p.created_at)

    async def add_session(self, session: CodingAgentSession) -> CodingAgentSession:
        self._sessions[session.id] = session
        self._events.setdefault(session.id, [])
        return session

    async def get_session(self, session_id: str) -> CodingAgentSession | None:
        return self._sessions.get(session_id)

    async def list_sessions(self) -> list[CodingAgentSession]:
        return sorted(self._sessions.values(), key=lambda s: s.started_at)

    async def update_session(self, session: CodingAgentSession) -> CodingAgentSession:
        self._sessions[session.id] = session
        return session

    async def add_event(self, event: CodingAgentEvent) -> CodingAgentEvent:
        self._events.setdefault(event.session_id, []).append(event)
        return event

    async def list_events(self, session_id: str) -> list[CodingAgentEvent]:
        return list(self._events.get(session_id, []))
