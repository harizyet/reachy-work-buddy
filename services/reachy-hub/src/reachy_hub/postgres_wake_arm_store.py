"""Postgres-backed WakeArmStore (migration 009). See wake_arm_store.py."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from reachy_hub.wake_arm_store import WakeArm
from shared.database import check_schema, connection_pool

_COLUMNS = "robot_id, user_id, arm_id, armed_at"
_UPSERT_SQL = f"""
INSERT INTO robot_wake_arm ({_COLUMNS}) VALUES (%s, %s, %s, %s)
ON CONFLICT (robot_id) DO UPDATE
SET user_id = EXCLUDED.user_id, arm_id = EXCLUDED.arm_id, armed_at = EXCLUDED.armed_at
"""


class PostgresWakeArmStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresWakeArmStore:
        pool = connection_pool(dsn)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def get(self, robot_id: str) -> WakeArm | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM robot_wake_arm WHERE robot_id = %s", (robot_id,))
            row = await cur.fetchone()
            return WakeArm(*row) if row else None

    async def list(self) -> list[WakeArm]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM robot_wake_arm ORDER BY robot_id")
            return [WakeArm(*row) for row in await cur.fetchall()]

    async def set(self, arm: WakeArm) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(_UPSERT_SQL, (arm.robot_id, arm.user_id, arm.arm_id, arm.armed_at))

    async def delete(self, robot_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM robot_wake_arm WHERE robot_id = %s", (robot_id,))
