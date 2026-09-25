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
from shared.models.websearch import (
    HostedSearchProvider,
    SearchConfig,
    SearchConfigPatch,
)

_COLUMNS = "policy, fallback, base_url, secret_ref, result_count, timeout_seconds, updated_at"


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
        # slot per provider identity, not per config row. Hosted providers
        # and the SearXNG fallback kinds share this namespace.
        return SecretContext("owner", f"websearch:{provider}", "api_key")

    async def _resolve(self, conn, provider, secret_ref) -> str | None:
        if secret_ref is None:
            return None
        return await self._secrets.resolve(conn, self._context(provider), secret_ref)

    async def _read(self, conn, lock: str):
        cur = await conn.execute(f"SELECT {_COLUMNS} FROM search_config WHERE id = 'default' {lock}")
        row = await cur.fetchone()
        cur = await conn.execute(
            f"SELECT provider, enabled, secret_ref, monthly_limit FROM search_provider {lock}"
        )
        hosted_rows = {r[0]: r[1:] for r in await cur.fetchall()}
        policy, fallback, base_url, secret_ref, result_count, timeout_seconds, updated_at = row
        hosted = {}
        for provider, (enabled, ref, monthly_limit) in hosted_rows.items():
            hosted[provider] = {
                "enabled": enabled, "monthly_limit": monthly_limit,
                "api_key": await self._resolve(conn, provider, ref),
            }
        try:
            config = SearchConfig.model_validate({
                "policy": policy, "fallback": fallback, "base_url": base_url,
                "api_key": await self._resolve(conn, fallback, secret_ref),
                "hosted": hosted, "result_count": result_count,
                "timeout_seconds": timeout_seconds, "updated_at": updated_at,
            })
        except ValidationError:
            raise SecretUnavailable() from None
        refs = {provider: values[1] for provider, values in hosted_rows.items()}
        return config, fallback, secret_ref, refs

    async def get(self) -> SearchConfig:
        async with self._pool.connection() as conn:
            config, *_ = await self._read(conn, "FOR SHARE")
            return config

    async def _store_secret(self, conn, provider, value, ref):
        if value is None:
            if ref is not None:
                await self._secrets.delete(conn, self._context(provider), ref)
            return None
        return await self._secrets.put(conn, self._context(provider), value, ref)

    async def set(self, patch: SearchConfigPatch) -> SearchConfig:
        async with self._pool.connection() as conn:
            current, current_fallback, current_ref, hosted_refs = await self._read(conn, "FOR UPDATE")
            config = merge_search_config(current, patch)
            if config.fallback != current_fallback and current_ref is not None:
                # A fallback switch always starts a fresh credential rather
                # than reusing a ref written under the old kind's context.
                await self._secrets.delete(conn, self._context(current_fallback), current_ref)
                current_ref = None
            ref = await self._store_secret(conn, config.fallback.value, config.api_key, current_ref)
            await conn.execute(
                """UPDATE search_config SET policy=%s, fallback=%s, base_url=%s, secret_ref=%s,
                result_count=%s, timeout_seconds=%s, updated_at=%s WHERE id = 'default'""",
                (config.policy.value, config.fallback.value, config.base_url, ref,
                 config.result_count, config.timeout_seconds, config.updated_at),
            )
            for kind, hosted in config.hosted.items():
                hosted_ref = await self._store_secret(conn, kind.value, hosted.api_key, hosted_refs.get(kind.value))
                await conn.execute(
                    "UPDATE search_provider SET enabled=%s, secret_ref=%s, monthly_limit=%s WHERE provider=%s",
                    (hosted.enabled, hosted_ref, hosted.monthly_limit, kind.value),
                )
            return config

    async def usage(self, period: str) -> dict[HostedSearchProvider, int]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT provider, used FROM search_usage WHERE period = %s", (period,))
            used = dict(await cur.fetchall())
        return {kind: used.get(kind.value, 0) for kind in HostedSearchProvider}

    async def reserve(self, provider: HostedSearchProvider, period: str, limit: int) -> bool:
        # One statement, so concurrent turns can never both take the last
        # call under the cap.
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """INSERT INTO search_usage (provider, period, used) VALUES (%s, %s, 1)
                ON CONFLICT (provider, period) DO UPDATE SET used = search_usage.used + 1
                WHERE search_usage.used < %s RETURNING used""",
                (provider.value, period, limit),
            )
            return await cur.fetchone() is not None

    async def exhaust(self, provider: HostedSearchProvider, period: str, limit: int) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """INSERT INTO search_usage (provider, period, used) VALUES (%s, %s, %s)
                ON CONFLICT (provider, period) DO UPDATE SET used = GREATEST(search_usage.used, EXCLUDED.used)""",
                (provider.value, period, limit),
            )
