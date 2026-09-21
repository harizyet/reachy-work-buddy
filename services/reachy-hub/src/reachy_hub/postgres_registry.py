"""Postgres-backed RobotRegistry. See robot_registry.py for the interface.

Per docs/plan.md §8, PostgreSQL holds "durable structured state and
metadata" — the robot registry is the first thing in this system that needs
to survive a reachy-hub restart, so it's the first real use of it.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from reachy_hub.robot_registry import Robot

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS robots (
    robot_id TEXT PRIMARY KEY,
    base_url TEXT NOT NULL
)
"""

_UPSERT_SQL = """
INSERT INTO robots (robot_id, base_url) VALUES (%s, %s)
ON CONFLICT (robot_id) DO UPDATE SET base_url = EXCLUDED.base_url
"""


class PostgresRobotRegistry:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresRobotRegistry:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        registry = cls(pool)
        async with pool.connection() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        return registry

    async def close(self) -> None:
        await self._pool.close()

    async def register(self, robot: Robot) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(_UPSERT_SQL, (robot.robot_id, robot.base_url))

    async def get(self, robot_id: str) -> Robot | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT robot_id, base_url FROM robots WHERE robot_id = %s", (robot_id,)
            )
            row = await cur.fetchone()
            return Robot(robot_id=row[0], base_url=row[1]) if row else None

    async def list(self) -> list[Robot]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT robot_id, base_url FROM robots ORDER BY robot_id")
            rows = await cur.fetchall()
            return [Robot(robot_id=r[0], base_url=r[1]) for r in rows]
