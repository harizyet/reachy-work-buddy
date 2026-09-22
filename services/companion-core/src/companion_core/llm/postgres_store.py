from datetime import datetime

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from companion_core.llm.store import merge_config, summarize
from shared.models.llm import LLMConfig, LLMConfigPatch, LLMUsageEntry


class PostgresLLMSettingsStore:
    def __init__(self, pool):
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str):
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        async with pool.connection() as conn:
            await conn.execute("""CREATE TABLE IF NOT EXISTS llm_config (
                id TEXT PRIMARY KEY DEFAULT 'default', config JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            await conn.execute(
                "INSERT INTO llm_config (id, config) VALUES ('default', %s) ON CONFLICT DO NOTHING",
                (Jsonb(LLMConfig().model_dump(mode="json")),),
            )
        return cls(pool)

    async def close(self):
        await self._pool.close()

    async def get(self) -> LLMConfig:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT config FROM llm_config WHERE id = 'default'"
            )
            return LLMConfig.model_validate((await cur.fetchone())[0])

    async def set(self, patch: LLMConfigPatch) -> LLMConfig:
        async with self._pool.connection() as conn:
            # Serialize partial updates so two tabs cannot lose each other's edits.
            cur = await conn.execute(
                "SELECT config FROM llm_config WHERE id = 'default' FOR UPDATE"
            )
            config = merge_config(
                LLMConfig.model_validate((await cur.fetchone())[0]), patch
            )
            await conn.execute(
                "UPDATE llm_config SET config = %s, updated_at = %s WHERE id = 'default'",
                (Jsonb(config.model_dump(mode="json")), config.updated_at),
            )
            return config


class PostgresLLMUsageStore:
    def __init__(self, pool):
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str):
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        async with pool.connection() as conn:
            await conn.execute("""CREATE TABLE IF NOT EXISTS llm_usage_log (
                id TEXT PRIMARY KEY, at TIMESTAMPTZ NOT NULL, role TEXT NOT NULL,
                model TEXT NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER,
                latency_ms DOUBLE PRECISION NOT NULL, success BOOLEAN NOT NULL, error_message TEXT)""")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS llm_usage_at_idx ON llm_usage_log (at DESC)"
            )
        return cls(pool)

    async def close(self):
        await self._pool.close()

    async def append(self, entry: LLMUsageEntry):
        async with self._pool.connection() as conn:
            await conn.execute(
                """INSERT INTO llm_usage_log
                (id, at, role, model, prompt_tokens, completion_tokens, latency_ms, success, error_message)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                tuple(entry.model_dump().values()),
            )

    @staticmethod
    def _entries(rows):
        fields = list(LLMUsageEntry.model_fields)
        return [LLMUsageEntry.model_validate(dict(zip(fields, row))) for row in rows]

    async def list_recent(self, limit: int) -> list[LLMUsageEntry]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM llm_usage_log ORDER BY at DESC LIMIT %s", (limit,)
            )
            return self._entries(await cur.fetchall())

    async def summary(self, since: datetime) -> dict:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM llm_usage_log WHERE at >= %s", (since,)
            )
            return summarize(self._entries(await cur.fetchall()))
