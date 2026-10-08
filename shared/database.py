"""Schema compatibility contract shared by SQL stores; no startup DDL."""

SCHEMA_REVISION = "027_knowledge_index"


async def check_schema(conn) -> None:
    cursor = await conn.execute("SELECT to_regclass('public.alembic_version')")
    if (await cursor.fetchone())[0] is None:
        raise RuntimeError("Database is unversioned; run the documented migration command first")
    cursor = await conn.execute("SELECT version_num FROM public.alembic_version")
    if await cursor.fetchall() != [(SCHEMA_REVISION,)]:
        raise RuntimeError("Database revision is incompatible; run the documented upgrade")


def connection_pool(dsn: str, *, min_size: int | None = None, max_size: int | None = None, **kwargs):
    """The one place a store's pool is sized. The homelab's single PostgreSQL has max_connections 100 and every store holds its own
    pool, so the library default (a fixed 4 per store, 92 connections idle across three services) left no headroom: see
    docs/verification/phase-44b-connection-budget-2026-10-08.md. Defaults are 1 idle and at most 3 per pool, tunable per service with
    DB_POOL_MIN_SIZE and DB_POOL_MAX_SIZE; a caller that knows better (the indexer) passes its own. Returns an unopened pool."""
    import os

    from psycopg_pool import AsyncConnectionPool

    low = min_size if min_size is not None else int(os.environ.get("DB_POOL_MIN_SIZE", "1"))
    high = max_size if max_size is not None else int(os.environ.get("DB_POOL_MAX_SIZE", "3"))
    return AsyncConnectionPool(dsn, open=False, min_size=low, max_size=max(low, high), **kwargs)
