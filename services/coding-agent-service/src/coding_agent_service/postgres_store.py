"""29.27: Postgres-backed CodingAgentStore. Each record is stored as its
validated pydantic JSON (`data`) beside the few columns that queries need,
so an additive optional model field needs no migration. The schema is owned
by companion-core's Alembic history (migration 013_coding_agent, ADR 0020);
this store only checks the revision and never runs DDL.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from shared.database import check_schema, connection_pool
from shared.models.coding_agent import (
    CodingAgentEvent,
    CodingAgentSession,
    CodingProject,
    UsageSnapshot,
)


def _json(model) -> Jsonb:
    return Jsonb(model.model_dump(mode="json"))


class PostgresCodingAgentStore:
    durable = True

    def __init__(self, dsn: str) -> None:
        # This service has exactly one store, so its one pool is already the service's shared pool. Nothing connects here:
        # constructing the app must not need a reachable database or a running event loop; open() runs in the app lifespan.
        self._pool = connection_pool(dsn)

    async def open(self) -> None:
        await self._pool.open()
        try:
            async with self._pool.connection() as conn:
                await check_schema(conn)
        except BaseException:
            await self._pool.close()
            raise

    async def close(self) -> None:
        await self._pool.close()

    async def add_project(self, project: CodingProject) -> CodingProject:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO coding_agent_projects (id, created_at, data) VALUES (%s, %s, %s)",
                (project.id, project.created_at, _json(project)),
            )
        return project

    async def get_project(self, project_id: str) -> CodingProject | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT data FROM coding_agent_projects WHERE id = %s", (project_id,))
            row = await cur.fetchone()
        return CodingProject.model_validate(row[0]) if row else None

    async def list_projects(self) -> list[CodingProject]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT data FROM coding_agent_projects ORDER BY created_at")
            rows = await cur.fetchall()
        return [CodingProject.model_validate(row[0]) for row in rows]

    async def add_session(self, session: CodingAgentSession) -> CodingAgentSession:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO coding_agent_sessions (id, project_id, status, started_at, data) "
                "VALUES (%s, %s, %s, %s, %s)",
                (session.id, session.project_id, session.status.value, session.started_at, _json(session)),
            )
        return session

    async def get_session(self, session_id: str) -> CodingAgentSession | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT data FROM coding_agent_sessions WHERE id = %s", (session_id,))
            row = await cur.fetchone()
        return CodingAgentSession.model_validate(row[0]) if row else None

    async def list_sessions(self) -> list[CodingAgentSession]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT data FROM coding_agent_sessions ORDER BY started_at, id")
            rows = await cur.fetchall()
        return [CodingAgentSession.model_validate(row[0]) for row in rows]

    async def update_session(self, session: CodingAgentSession) -> CodingAgentSession:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE coding_agent_sessions SET status = %s, data = %s WHERE id = %s",
                (session.status.value, _json(session), session.id),
            )
        return session

    async def add_event(self, event: CodingAgentEvent) -> CodingAgentEvent:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO coding_agent_events (id, session_id, data) VALUES (%s, %s, %s)",
                (event.id, event.session_id, _json(event)),
            )
        return event

    async def list_events(self, session_id: str) -> list[CodingAgentEvent]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT data FROM coding_agent_events WHERE session_id = %s ORDER BY sequence", (session_id,)
            )
            rows = await cur.fetchall()
        return [CodingAgentEvent.model_validate(row[0]) for row in rows]

    async def add_usage_snapshot(self, snapshot: UsageSnapshot) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO coding_agent_usage_snapshots (session_id, provider, measured_at, data) "
                "VALUES (%s, %s, %s, %s)",
                (snapshot.session_id, snapshot.provider, snapshot.measured_at, _json(snapshot)),
            )

    async def latest_usage_snapshot(self, session_id: str) -> UsageSnapshot | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT data FROM coding_agent_usage_snapshots WHERE session_id = %s "
                "ORDER BY sequence DESC LIMIT 1",
                (session_id,),
            )
            row = await cur.fetchone()
        return UsageSnapshot.model_validate(row[0]) if row else None

    async def recent_usage_snapshots(self, provider: str, limit: int) -> list[UsageSnapshot]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT data FROM coding_agent_usage_snapshots WHERE provider = %s "
                "ORDER BY sequence DESC LIMIT %s",
                (provider, limit),
            )
            rows = await cur.fetchall()
        return [UsageSnapshot.model_validate(row[0]) for row in rows]
