"""Schema compatibility contract shared by SQL stores; no startup DDL."""

from __future__ import annotations

SCHEMA_REVISION = "028_memory_candidates"


async def check_schema(conn) -> None:
    cursor = await conn.execute("SELECT to_regclass('public.alembic_version')")
    if (await cursor.fetchone())[0] is None:
        raise RuntimeError("Database is unversioned; run the documented migration command first")
    cursor = await conn.execute("SELECT version_num FROM public.alembic_version")
    if await cursor.fetchall() != [(SCHEMA_REVISION,)]:
        raise RuntimeError("Database revision is incompatible; run the documented upgrade")


def connection_pool(dsn: str, *, min_size: int | None = None, max_size: int | None = None, **kwargs):
    """Build an unopened pool. Application code does not call this directly: a service owns one DatabaseManager and its stores share the
    manager's pool (Phase 45, docs/phase-45.md). Defaults are 1 idle and at most 8 connections, tunable per service with DB_POOL_MIN_SIZE
    and DB_POOL_MAX_SIZE; a caller that knows better passes its own."""
    import os

    from psycopg_pool import AsyncConnectionPool

    if os.environ.get("DB_PREPARE_THRESHOLD", "").lower() in ("off", "none", "never"):
        # Server-side prepared statements live on one backend; behind a transaction-pooling intermediary that does not track them, turn them off.
        kwargs.setdefault("kwargs", {})["prepare_threshold"] = None
    low = min_size if min_size is not None else int(os.environ.get("DB_POOL_MIN_SIZE", "1"))
    high = max_size if max_size is not None else int(os.environ.get("DB_POOL_MAX_SIZE", "8"))
    return AsyncConnectionPool(
        dsn, open=False, min_size=low, max_size=max(low, high),
        timeout=float(os.environ.get("DB_POOL_TIMEOUT_SECONDS", "10")),  # bounded wait for a connection; the library default is 30
        max_lifetime=float(os.environ.get("DB_POOL_MAX_LIFETIME_SECONDS", "1800")), max_idle=float(os.environ.get("DB_POOL_MAX_IDLE_SECONDS", "300")),
        check=AsyncConnectionPool.check_connection,  # a restarted PostgreSQL or PgBouncer breaks idle connections; test one before handing it out
        **kwargs,
    )


class DatabaseManager:
    """One pool per service process, shared by every store in it. The manager opens it (checking the schema revision once, so a service on
    the wrong revision refuses to start) and closes it after the stores; stores never open or close a shared pool. A pool belongs to the
    event loop that opened it, so a separate worker process or loop builds its own manager."""

    def __init__(self, dsn: str, *, vector: bool = False, min_size: int | None = None, max_size: int | None = None) -> None:
        self.dsn, self.vector = dsn, vector
        kwargs = {}
        if vector:
            from pgvector.psycopg import register_vector_async

            kwargs["configure"] = register_vector_async  # every connection learns the vector type; the stores that need it share the pool
        self.pool = connection_pool(dsn, min_size=min_size, max_size=max_size, **kwargs)
        self.pool.shared = True  # marks it for close_pool: a store holding a shared pool must not close it

    async def start(self) -> DatabaseManager:
        if self.vector:
            await _check_revision_first(self.dsn)
        await self.pool.open()
        try:
            async with self.pool.connection() as conn:
                await check_schema(conn)
        except BaseException:
            await self.pool.close()
            raise
        return self

    async def stop(self) -> None:
        await self.pool.close()


async def _check_revision_first(dsn: str) -> None:
    """Before the vector type is registered, so an unversioned database fails with the migration message, not a missing-type error."""
    import psycopg

    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=10) as conn:
        await check_schema(conn)


async def open_pool(source, *, vector: bool = False, **pool_kwargs):
    """What a store's connect() uses. A DatabaseManager gives its shared, already-open pool; a DSN string builds, opens and schema-checks a
    pool the store owns (tests and standalone tools)."""
    if isinstance(source, DatabaseManager):
        if vector and not source.vector:
            raise RuntimeError("this store needs the vector type registered: build the DatabaseManager with vector=True")
        return source.pool
    if vector:
        from pgvector.psycopg import register_vector_async

        await _check_revision_first(source)
        pool_kwargs["configure"] = register_vector_async
    pool = connection_pool(source, **pool_kwargs)
    await pool.open()
    return pool


async def close_pool(pool) -> None:
    """Close a pool a store owns; leave a shared one to its DatabaseManager."""
    if not getattr(pool, "shared", False):
        await pool.close()
