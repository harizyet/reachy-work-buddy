from psycopg_pool import AsyncConnectionPool

from companion_core.persona.store import merge_persona
from shared.database import check_schema
from shared.models.persona import PersonaConfig, PersonaPatch


class PostgresPersonaStore:
    def __init__(self, pool):
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str):
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        try:
            async with pool.connection() as conn:
                await check_schema(conn)
            return cls(pool)
        except BaseException:
            await pool.close()
            raise

    async def close(self):
        await self._pool.close()

    async def get(self) -> PersonaConfig:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, system_prompt FROM persona_config WHERE id = 'default' FOR SHARE"
            )
            name, system_prompt = await cur.fetchone()
            return PersonaConfig(name=name, system_prompt=system_prompt)

    async def set(self, patch: PersonaPatch) -> PersonaConfig:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, system_prompt FROM persona_config WHERE id = 'default' FOR UPDATE"
            )
            name, system_prompt = await cur.fetchone()
            current = PersonaConfig(name=name, system_prompt=system_prompt)
            config = merge_persona(current, patch)
            await conn.execute(
                "UPDATE persona_config SET name = %s, system_prompt = %s, updated_at = now() WHERE id = 'default'",
                (config.name, config.system_prompt),
            )
            return config
