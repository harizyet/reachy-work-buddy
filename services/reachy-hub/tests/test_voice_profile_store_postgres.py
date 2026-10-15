"""Encrypted voice profiles against a real PostgreSQL, using the real migration 038 statements: one owner profile, in-place
re-enrolment, deletion, and ciphertext-only storage (ADR 0041)."""

import asyncio
import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from reachy_hub.keyring import Keyring
from reachy_hub.voice_profiles import PostgresVoiceProfileStore, load_template, seal

from shared.models.voice_identity import ClientKind, ClientProvenance

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="needs a disposable Postgres")
KEYRING = Keyring("k1", {"k1": bytes(range(32))})
PHONE = ClientProvenance(client_kind=ClientKind.ANDROID, client_id="install-1")
MIGRATION = Path(__file__).parents[2] / "companion-core/src/companion_core/migrations/versions/038_voice_profiles.py"


def migration_statements() -> list[str]:
    spec = importlib.util.spec_from_file_location("m038", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._UP


@pytest.fixture
def database():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "voice_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    dsn = psycopg.conninfo.make_conninfo(root, dbname=name)
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in migration_statements():
            conn.execute(statement)
    try:
        yield dsn
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def sealed(template, owner="owner"):
    return seal(KEYRING, owner_id=owner, model_version="m@1", template=template, sample_count=5, enrolled_by=PHONE, consented_at=datetime.now(UTC))


def test_profile_lifecycle_and_ciphertext_only_storage(database):
    async def scenario() -> None:
        pool = AsyncConnectionPool(database, open=False)
        await pool.open()
        store = PostgresVoiceProfileStore(pool)
        try:
            first = await store.put(sealed([0.6, 0.8]))
            assert first.version == 1 and load_template(KEYRING, await store.get("owner")) == [0.6, 0.8]
            async with pool.connection() as conn:
                row = await (await conn.execute("SELECT ciphertext FROM voice_profiles")).fetchone()
            assert b"0.6" not in bytes(row[0])
            second = await store.put(sealed([0.8, 0.6]))  # re-enrolment replaces in place
            assert second.version == 2 and second.profile_id != first.profile_id
            async with pool.connection() as conn:
                assert (await (await conn.execute("SELECT count(*) FROM voice_profiles")).fetchone())[0] == 1
            assert await store.get("someone-else") is None
            assert await store.delete("owner") is True and await store.delete("owner") is False and await store.get("owner") is None
        finally:
            await pool.close()

    asyncio.run(scenario())
