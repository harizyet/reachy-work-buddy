"""29.1/29.27: project/session/event/usage store interface plus the
in-memory implementation used by tests and by a deployment with no
DATABASE_URL. postgres_store.py is the durable implementation behind the
same Protocol (same precedent as companion-core's tasks/calendar/meetings
stores). `durable` tells the app whether there is previous-process state to
recover at startup.
"""

from __future__ import annotations

from typing import Protocol

from shared.models.coding_agent import (
    CodingAgentEvent,
    CodingAgentSession,
    CodingProject,
    UsageSnapshot,
)


class CodingAgentStore(Protocol):
    durable: bool

    async def add_project(self, project: CodingProject) -> CodingProject: ...
    async def get_project(self, project_id: str) -> CodingProject | None: ...
    async def list_projects(self) -> list[CodingProject]: ...

    async def add_session(self, session: CodingAgentSession) -> CodingAgentSession: ...
    async def get_session(self, session_id: str) -> CodingAgentSession | None: ...
    async def list_sessions(self) -> list[CodingAgentSession]: ...
    async def update_session(self, session: CodingAgentSession) -> CodingAgentSession: ...

    async def add_event(self, event: CodingAgentEvent) -> CodingAgentEvent: ...
    async def list_events(self, session_id: str) -> list[CodingAgentEvent]: ...

    async def add_usage_snapshot(self, snapshot: UsageSnapshot) -> None: ...
    async def latest_usage_snapshot(self, session_id: str) -> UsageSnapshot | None: ...
    async def recent_usage_snapshots(self, provider: str, limit: int) -> list[UsageSnapshot]:
        """Newest first, across every session of one provider."""
        ...


class InMemoryCodingAgentStore:
    durable = False

    def __init__(self) -> None:
        self._projects: dict[str, CodingProject] = {}
        self._sessions: dict[str, CodingAgentSession] = {}
        self._events: dict[str, list[CodingAgentEvent]] = {}
        self._usage: list[UsageSnapshot] = []

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

    async def add_usage_snapshot(self, snapshot: UsageSnapshot) -> None:
        self._usage.append(snapshot)

    async def latest_usage_snapshot(self, session_id: str) -> UsageSnapshot | None:
        for snapshot in reversed(self._usage):
            if snapshot.session_id == session_id:
                return snapshot
        return None

    async def recent_usage_snapshots(self, provider: str, limit: int) -> list[UsageSnapshot]:
        return [s for s in reversed(self._usage) if s.provider == provider][:limit]
