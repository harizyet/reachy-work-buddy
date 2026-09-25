from psycopg_pool import AsyncConnectionPool

from companion_core.persona.store import merge_persona
from shared.database import check_schema
from shared.models.persona import PersonaConfig, PersonaPatch

_FIELDS = ("name", "system_prompt", "location", "timezone")
_COLUMNS = ", ".join(_FIELDS)


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
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM persona_config WHERE id = 'default' FOR SHARE")
            return PersonaConfig(**dict(zip(_FIELDS, await cur.fetchone(), strict=True)))

    async def set(self, patch: PersonaPatch) -> PersonaConfig:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM persona_config WHERE id = 'default' FOR UPDATE")
            current = PersonaConfig(**dict(zip(_FIELDS, await cur.fetchone(), strict=True)))
            config = merge_persona(current, patch)
            await conn.execute(
                """UPDATE persona_config SET name = %s, system_prompt = %s, location = %s, timezone = %s,
                updated_at = now() WHERE id = 'default'""",
                (config.name, config.system_prompt, config.location, config.timezone),
            )
            return config
