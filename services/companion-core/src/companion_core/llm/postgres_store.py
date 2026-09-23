from datetime import datetime

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from companion_core.llm.store import merge_config, summarize
from companion_core.secrets import (
    Keyring,
    PostgresSecretStore,
    SecretContext,
    SecretUnavailable,
)
from shared.database import check_schema
from shared.models.llm import LLMConfig, LLMConfigPatch, LLMUsageEntry


class PostgresLLMSettingsStore:
    def __init__(self, pool, secret_store):
        self._pool = pool
        self._secrets = secret_store

    @classmethod
    async def connect(cls, dsn: str, *, keyring: Keyring | None = None):
        secrets = PostgresSecretStore(keyring or Keyring.from_file())
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        try:
            async with pool.connection() as conn:
                await check_schema(conn)
            return cls(pool, secrets)
        except BaseException:
            await pool.close()
            raise

    async def close(self):
        await self._pool.close()

    @staticmethod
    def _context(role):
        return SecretContext("owner", f"llm:{role}", "api_key")

    async def _resolve(self, conn, data):
        # Never accept legacy plaintext after the coordinated cutover.
        for role in ("local", "cloud"):
            provider = data.get(role)
            if provider is not None:
                if "api_key" in provider:
                    raise SecretUnavailable()
                ref = provider.pop("secret_ref", None)
                provider["api_key"] = (
                    await self._secrets.resolve(conn, self._context(role), ref)
                    if ref is not None else None
                )
        try:
            return LLMConfig.model_validate(data)
        except ValidationError:
            raise SecretUnavailable() from None

    async def get(self) -> LLMConfig:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT config FROM llm_config WHERE id = 'default' FOR SHARE")
            return await self._resolve(conn, (await cur.fetchone())[0])

    async def set(self, patch: LLMConfigPatch) -> LLMConfig:
        async with self._pool.connection() as conn:
            # Config always locks before secrets; migration/rotation never locks config
            # after taking secret locks. This preserves partial-update serialization.
            cur = await conn.execute(
                "SELECT config FROM llm_config WHERE id = 'default' FOR UPDATE"
            )
            data = (await cur.fetchone())[0]
            refs = {
                role: (data.get(role) or {}).get("secret_ref")
                for role in ("local", "cloud")
            }
            current = await self._resolve(conn, data)
            config = merge_config(current, patch)
            stored = config.model_dump(mode="json")
            for role in ("local", "cloud"):
                provider = stored[role]
                ref = refs[role]
                value = provider.pop("api_key") if provider is not None else None
                if value is None:
                    if ref is not None:
                        await self._secrets.delete(conn, self._context(role), ref)
                    ref = None
                else:
                    ref = await self._secrets.put(conn, self._context(role), value, ref)
                if provider is not None:
                    provider["secret_ref"] = ref
            await conn.execute(
                "UPDATE llm_config SET config = %s, updated_at = %s WHERE id = 'default'",
                (Jsonb(stored), config.updated_at),
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
            await check_schema(conn)
        return cls(pool)

    async def close(self):
        await self._pool.close()

    async def append(self, entry: LLMUsageEntry):
        async with self._pool.connection() as conn:
            await conn.execute(
                """INSERT INTO llm_usage_log
                (id, at, role, model, prompt_tokens, completion_tokens, latency_ms, success, error_message, escalation_reason)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                tuple(entry.model_dump().values()),
            )

    @staticmethod
    def _entries(rows):
        return [LLMUsageEntry.model_validate(row) for row in rows]

    async def list_recent(self, limit: int) -> list[LLMUsageEntry]:
        async with self._pool.connection() as conn:
            conn.row_factory = dict_row
            cur = await conn.execute(
                "SELECT * FROM llm_usage_log ORDER BY at DESC LIMIT %s", (limit,)
            )
            return self._entries(await cur.fetchall())

    async def summary(self, since: datetime) -> dict:
        async with self._pool.connection() as conn:
            conn.row_factory = dict_row
            cur = await conn.execute(
                "SELECT * FROM llm_usage_log WHERE at >= %s", (since,)
            )
            return summarize(self._entries(await cur.fetchall()))
