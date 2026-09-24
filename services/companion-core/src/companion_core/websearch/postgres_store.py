from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from companion_core.secrets import (
    Keyring,
    PostgresSecretStore,
    SecretContext,
    SecretUnavailable,
)
from companion_core.websearch.store import merge_search_config
from shared.database import check_schema
from shared.models.websearch import SearchConfig, SearchConfigPatch

_COLUMNS = "policy, provider, base_url, secret_ref, result_count, timeout_seconds, updated_at"


class PostgresSearchSettingsStore:
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
    def _context(provider) -> SecretContext:
        # Mirrors llm/postgres_store.py's f"llm:{role}" — one credential
        # slot per provider identity, not per config row.
        return SecretContext("owner", f"websearch:{provider}", "api_key")

    async def _row_to_config(self, conn, row) -> SearchConfig:
        policy, provider, base_url, secret_ref, result_count, timeout_seconds, updated_at = row
        api_key = (
            await self._secrets.resolve(conn, self._context(provider), secret_ref)
            if secret_ref is not None
            else None
        )
        try:
            return SearchConfig.model_validate({
                "policy": policy, "provider": provider, "base_url": base_url,
                "api_key": api_key, "result_count": result_count,
                "timeout_seconds": timeout_seconds, "updated_at": updated_at,
            })
        except ValidationError:
            raise SecretUnavailable() from None

    async def get(self) -> SearchConfig:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM search_config WHERE id = 'default' FOR SHARE"
            )
            return await self._row_to_config(conn, await cur.fetchone())

    async def set(self, patch: SearchConfigPatch) -> SearchConfig:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM search_config WHERE id = 'default' FOR UPDATE"
            )
            row = await cur.fetchone()
            current_provider, current_ref = row[1], row[3]
            current = await self._row_to_config(conn, row)
            config = merge_search_config(current, patch)
            provider_changed = config.provider != current_provider
            if provider_changed and current_ref is not None:
                # A provider switch always starts a fresh credential rather
                # than reusing a ref written under the old provider's context.
                await self._secrets.delete(conn, self._context(current_provider), current_ref)
                current_ref = None
            if config.api_key is None:
                if current_ref is not None:
                    await self._secrets.delete(conn, self._context(current_provider), current_ref)
                ref = None
            else:
                ref = await self._secrets.put(conn, self._context(config.provider), config.api_key, current_ref)
            await conn.execute(
                """UPDATE search_config SET policy=%s, provider=%s, base_url=%s, secret_ref=%s,
                result_count=%s, timeout_seconds=%s, updated_at=%s WHERE id = 'default'""",
                (config.policy.value, config.provider.value, config.base_url, ref,
                 config.result_count, config.timeout_seconds, config.updated_at),
            )
            return config
