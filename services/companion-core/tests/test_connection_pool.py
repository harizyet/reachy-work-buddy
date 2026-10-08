"""Phase 45 connection architecture (docs/phase-45.md): one pool per service process, injected into the stores, bounded and self-healing.
The first group needs no database. The second needs a disposable Postgres with pgvector (DATABASE_MIGRATION_TEST_URL)."""

import asyncio
import os
import pathlib
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from companion_core import migrations
from companion_core.knowledge.index import PostgresKnowledgeIndex
from companion_core.knowledge.outbox import PostgresOutbox
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.secrets import Keyring
from companion_core.tasks.postgres_store import PostgresTaskStore
from psycopg_pool import PoolTimeout
from sqlalchemy import create_engine

from shared.database import DatabaseManager, close_pool, connection_pool, open_pool

ROOT = pathlib.Path(__file__).resolve().parents[3]
KEYS = Keyring("one", {"one": b"\x01" * 32})
needs_db = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")


def test_default_pool_is_bounded_and_unopened(monkeypatch) -> None:
    for name in ("DB_POOL_MIN_SIZE", "DB_POOL_MAX_SIZE", "DB_POOL_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    pool = connection_pool("postgresql://u:p@localhost/db")
    assert (pool.min_size, pool.max_size, pool.timeout) == (1, 8, 10.0) and pool._opened is False  # nothing connects until opened


def test_environment_tunes_the_default_and_a_caller_can_override(monkeypatch) -> None:
    monkeypatch.setenv("DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "5")
    pool = connection_pool("postgresql://x/y")
    assert (pool.min_size, pool.max_size) == (2, 5)
    assert connection_pool("postgresql://x/y", max_size=3).max_size == 3
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "1")  # a maximum below the minimum never produces an invalid pool
    assert connection_pool("postgresql://x/y").max_size == 2


def test_a_shared_pool_is_never_closed_by_a_store() -> None:
    class Spy:
        closed = False

        async def close(self):
            self.closed = True

    shared, owned = Spy(), Spy()
    shared.shared = True
    asyncio.run(close_pool(shared))
    asyncio.run(close_pool(owned))
    assert (shared.closed, owned.closed) == (False, True)
    assert DatabaseManager("postgresql://x/y").pool.shared is True


def test_only_the_shared_module_builds_pools() -> None:
    offenders = []
    for path in (ROOT / "services").rglob("*.py"):
        if {"tests", "benchmarks", ".venv"} & set(path.parts):
            continue
        text = path.read_text()
        if "AsyncConnectionPool(" in text:
            offenders.append(str(path.relative_to(ROOT)))
        if "connection_pool(" in text and "coding_agent_service" not in str(path):
            offenders.append(str(path.relative_to(ROOT)))  # stores go through open_pool / the manager; only coding-agent owns its single pool
    assert offenders == [], f"size pools through shared.database (DatabaseManager or open_pool): {offenders}"


@pytest.fixture
def database():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    try:
        yield psycopg.conninfo.make_conninfo(root, dbname=name), root
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def migrate(dsn: str) -> None:
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), hide_parameters=True)
    try:
        with engine.begin() as conn:
            config = Config()
            config.set_main_option("script_location", str(pathlib.Path(migrations.__file__).parent))
            config.attributes.update(connection=conn, keyring=KEYS, adopt_legacy=False)
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def backends(root: str, dsn: str) -> int:
    name = psycopg.conninfo.conninfo_to_dict(dsn)["dbname"]
    with psycopg.connect(root, autocommit=True) as conn:
        return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,)).fetchone()[0]


@needs_db
def test_every_store_shares_one_bounded_pool_and_shutdown_releases_it(database, tmp_path) -> None:
    dsn, root = database
    migrate(dsn)

    async def go():
        manager = await DatabaseManager(dsn, vector=True, max_size=4).start()
        stores = [await PostgresMemoryStore.connect(manager), await PostgresPlannerStore.connect(manager), await PostgresTaskStore.connect(manager),
                  await PostgresDocumentStore.connect(manager, embed_fn=lambda t: [[0.0] * 384 for _ in t]),
                  await PostgresKnowledgeIndex.connect(manager), await PostgresOutbox.connect(manager)]
        assert {id(s._pool) for s in stores} == {id(manager.pool)}  # one pool, not six

        async def work(i):
            await stores[0].add_memory(content=f"fact {i}", source="test")
            await stores[2].add_task(text=f"task {i}")
            await stores[1].list_notes()
        peak = 0

        async def watch():
            nonlocal peak
            while True:
                peak = max(peak, await asyncio.to_thread(backends, root, dsn))
                await asyncio.sleep(0.02)
        watcher = asyncio.create_task(watch())
        await asyncio.gather(*(work(i) for i in range(60)))  # 60 concurrent operations through a pool of at most 4
        watcher.cancel()
        assert 1 <= peak <= 4
        for s in stores:
            await s.close()  # a store closing must leave the shared pool usable
        async with manager.pool.connection() as conn:
            assert (await (await conn.execute("SELECT 1")).fetchone())[0] == 1
        await manager.stop()

    asyncio.run(go())
    assert backends(root, dsn) == 0


@needs_db
def test_waiting_for_a_connection_is_bounded_and_the_pool_heals_after_a_server_side_kill(database, monkeypatch) -> None:
    dsn, root = database
    migrate(dsn)
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "1")

    async def go():
        manager = await DatabaseManager(dsn, max_size=1).start()
        async with manager.pool.connection():  # hold the only connection
            started = asyncio.get_running_loop().time()
            with pytest.raises(PoolTimeout):
                async with manager.pool.connection():
                    pass
            assert asyncio.get_running_loop().time() - started < 3  # bounded, not the library's 30 s
        with psycopg.connect(root, autocommit=True) as conn:  # the server (or a pooler restart) kills every pooled backend
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                         (psycopg.conninfo.conninfo_to_dict(dsn)["dbname"],))
        async with manager.pool.connection() as conn:  # the next use gets a fresh connection, no manual step
            assert (await (await conn.execute("SELECT 1")).fetchone())[0] == 1
        await manager.stop()

    asyncio.run(go())


@needs_db
def test_vector_stores_require_a_vector_manager_and_an_unmigrated_database_fails_clearly(database) -> None:
    dsn, root = database

    async def unmigrated():
        with pytest.raises(RuntimeError, match="unversioned|migration"):
            await DatabaseManager(dsn, vector=True).start()

    asyncio.run(unmigrated())
    migrate(dsn)

    async def wrong_manager():
        manager = await DatabaseManager(dsn, vector=False).start()
        with pytest.raises(RuntimeError, match="vector"):
            await open_pool(manager, vector=True)
        await manager.stop()

    asyncio.run(wrong_manager())
    assert backends(root, dsn) == 0
