"""Phase 45C: the constructs this codebase relies on, exercised THROUGH a transaction-pooling PgBouncer (docs/phase-45.md section 3).
Opt-in: DATABASE_POOLER_TEST_URL is a DSN (any database name) for a PgBouncer in transaction mode whose [databases] section has a wildcard entry
for the disposable PostgreSQL that DATABASE_MIGRATION_TEST_URL names; each test makes and migrates its own database directly, then works through
the pooler. Set
DATABASE_POOLER_PREPARED=1 when the pooler has max_prepared_statements > 0 and the driver should prepare; otherwise preparation is turned off,
which is the setting for a pooler without protocol-level prepared statements."""

import asyncio
import os
import pathlib
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from companion_core import migrations
from companion_core.knowledge.outbox import PostgresOutbox
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.secrets import Keyring
from companion_core.tasks.postgres_store import PostgresTaskStore
from sqlalchemy import create_engine

from shared.database import DatabaseManager

ROOT = pathlib.Path(__file__).resolve().parents[3]
POOLER = os.environ.get("DATABASE_POOLER_TEST_URL")
DIRECT = os.environ.get("DATABASE_MIGRATION_TEST_URL")
needs_pooler = pytest.mark.skipif(not (POOLER and DIRECT), reason="requires a transaction-pooling PgBouncer and a disposable PostgreSQL behind it")


def test_the_code_uses_only_constructs_that_survive_transaction_pooling() -> None:
    """Static rules from the audit: no session-level SET, advisory locks, LISTEN/NOTIFY, temp tables or named cursors in application code."""
    banned = {
        "session-level SET": re.compile(r"""["'\s]SET\s+(?!LOCAL\b)(?!search_path\s+TO\s+migration)[a-z_.]+\s*(=|TO)\b""", re.IGNORECASE),
        "advisory lock": re.compile(r"pg_(try_)?advisory", re.IGNORECASE),
        "LISTEN/NOTIFY": re.compile(r"""["']\s*(LISTEN|NOTIFY)\s+\w+\s*["';]|pg_notify""", re.IGNORECASE),
        "temp table": re.compile(r"CREATE\s+TEMP", re.IGNORECASE),
        "named cursor": re.compile(r"\.cursor\(\s*name\s*=|DECLARE\s+\w+\s+CURSOR", re.IGNORECASE),
    }
    hits = []
    for path in (ROOT / "services").rglob("*.py"):
        if {"tests", "benchmarks", ".venv", "versions"} & set(path.parts):
            continue
        if "migrations" in path.parts:
            continue  # the migration job takes an advisory lock and runs on the direct PostgreSQL path by design (docs/phase-45.md section 4)
        text = path.read_text()
        for label, pattern in banned.items():
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                snippet = text.splitlines()[line - 1].strip()
                if "ON CONFLICT" in snippet or "DO UPDATE SET" in snippet or snippet.startswith(("#", '"""')):
                    continue
                hits.append(f"{path.relative_to(ROOT)}:{line} {label}: {snippet[:80]}")
    assert hits == [], "\n".join(hits)
    assert "pg_try_advisory_lock" in (ROOT / "services/companion-core/src/companion_core/migrations/__main__.py").read_text()  # still true: direct only


KEYS = Keyring("one", {"one": b"\x01" * 32})


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


@pytest.fixture
def pooled():
    """A freshly migrated database, made directly, and the DSN that reaches it through the pooler."""
    name = "test_" + uuid4().hex
    with psycopg.connect(DIRECT, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    migrate(psycopg.conninfo.make_conninfo(DIRECT, dbname=name))
    try:
        yield psycopg.conninfo.make_conninfo(POOLER, dbname=name)
    finally:
        with psycopg.connect(DIRECT, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def prepare_kwargs() -> dict:
    return {} if os.environ.get("DATABASE_POOLER_PREPARED") == "1" else {"kwargs": {"prepare_threshold": None}}


async def manager(dsn: str, max_size: int = 4, vector: bool = True) -> DatabaseManager:  # callers stop it in a finally block
    if prepare_kwargs():
        os.environ["DB_PREPARE_THRESHOLD"] = "off"
    else:
        os.environ.pop("DB_PREPARE_THRESHOLD", None)
    return await DatabaseManager(dsn, vector=vector, max_size=max_size).start()


@needs_pooler
def test_repeated_statements_prepared_or_not_and_pgvector_and_set_local_through_the_pooler(pooled) -> None:
    async def go():
        dsn = pooled
        m = await manager(dsn, max_size=1)  # one client connection: every statement and transaction reuses it
        try:
            async with m.pool.connection() as conn:
                for i in range(30):  # past the driver's prepare threshold of 5
                    assert (await (await conn.execute("SELECT %s::int + 1", (i,))).fetchone())[0] == i + 1
                await conn.commit()  # end the implicit transaction the loop opened: conn.transaction() would otherwise be only a savepoint
                async with conn.transaction():
                    await conn.execute("SET LOCAL hnsw.ef_search = 77")
                    assert (await (await conn.execute("SHOW hnsw.ef_search")).fetchone())[0] == "77"
                assert (await (await conn.execute("SHOW hnsw.ef_search")).fetchone())[0] != "77"  # SET LOCAL ended with its transaction
                async with conn.transaction():
                    await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
                    cur = await conn.execute("SELECT count(*) FROM (SELECT ref_key FROM knowledge_items ORDER BY embedding <=> %s::vector LIMIT 5) q",
                                             ("[" + ",".join(["0.1"] * 384) + "]",))
                    assert (await cur.fetchone())[0] >= 0  # the vector operator and the registered type work through the pooler
        finally:
            await m.stop()

    asyncio.run(go())


@needs_pooler
def test_two_workers_never_claim_the_same_outbox_row_through_the_pooler(pooled) -> None:
    async def go():
        dsn = pooled
        m = await manager(dsn, max_size=4)
        try:
            outbox = await PostgresOutbox.connect(m)
            now = datetime.now(UTC) + timedelta(seconds=60)  # the database stamps rows with its own clock; claim as of a minute from now
            tag = uuid4().hex
            ids = [f"{tag}-{i}" for i in range(40)]
            for sid in ids:
                await outbox.enqueue("note", sid, now)
            got = await asyncio.gather(*[outbox.claim(now, lease_seconds=60, limit=10) for _ in range(6)])  # six concurrent workers
            claimed = [item.source_id for batch in got for item in batch if item.source_id in ids]
            assert len(claimed) == len(set(claimed)) == 40  # every row claimed exactly once
            for batch in got:
                for item in batch:
                    await outbox.complete(item, now)
        finally:
            await m.stop()

    asyncio.run(go())


@needs_pooler
def test_a_due_reminder_is_claimed_once_by_concurrent_pollers_through_the_pooler(pooled) -> None:
    async def go():
        dsn = pooled
        m = await manager(dsn, max_size=4)
        try:
            planner = await PostgresPlannerStore.connect(m)
            reminder = await planner.add_reminder(text=f"pooler claim {uuid4().hex}", due_at=datetime.now(UTC) - timedelta(minutes=1))
            got = await asyncio.gather(*[planner.claim_due(datetime.now(UTC)) for _ in range(8)])
            assert sum(r.id == reminder.id for batch in got for r in batch) == 1  # claim-once survives concurrency and pooling
            await planner.delete_reminder(reminder.id)
        finally:
            await m.stop()

    asyncio.run(go())


@needs_pooler
def test_a_rolled_back_transaction_leaves_nothing_and_the_connection_stays_usable(pooled) -> None:
    async def go():
        dsn = pooled
        m = await manager(dsn, max_size=1)
        try:
            tasks = await PostgresTaskStore.connect(m)
            task = await tasks.add_task(text=f"rollback {uuid4().hex}")
            with pytest.raises(RuntimeError):
                async with m.pool.connection() as conn, conn.transaction():
                    await conn.execute("UPDATE tasks SET text = 'changed inside the transaction' WHERE id = %s", (task.id,))
                    raise RuntimeError("abort")
            assert [t.text for t in await tasks.list_tasks(None) if t.id == task.id] == [task.text]  # the update did not survive
            again = await tasks.add_task(text="after the rollback")  # the same single connection works normally
            assert again.text == "after the rollback"
        finally:
            await m.stop()

    asyncio.run(go())


@needs_pooler
def test_the_pool_survives_a_pooler_side_disconnect(pooled) -> None:
    async def go():
        dsn = pooled
        m = await manager(dsn, max_size=1)
        try:
            async with m.pool.connection() as conn:
                assert (await (await conn.execute("SELECT 1")).fetchone())[0] == 1
            with psycopg.connect(psycopg.conninfo.make_conninfo(pooled, dbname="pgbouncer"), autocommit=True) as admin:  # PgBouncer admin console
                name = psycopg.conninfo.conninfo_to_dict(pooled)["dbname"]
                admin.execute(psycopg.sql.SQL("KILL {}").format(psycopg.sql.Identifier(name)))  # drop every client and server connection; new clients wait
                admin.execute(psycopg.sql.SQL("RESUME {}").format(psycopg.sql.Identifier(name)))
            async with m.pool.connection() as conn:  # the check on checkout replaces the dead connection
                assert (await (await conn.execute("SELECT 2")).fetchone())[0] == 2
        finally:
            await m.stop()

    asyncio.run(go())
