"""Opt-in real Postgres checks. DATABASE_MIGRATION_TEST_URL must be disposable."""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest
from companion_core.llm.postgres_store import PostgresLLMSettingsStore
from companion_core.llm.store import masked_config
from companion_core.migrations.__main__ import LOCK_ID, upgrade
from companion_core.migrations.legacy import BASELINE
from companion_core.secrets import (
    Keyring,
    PostgresSecretStore,
    SecretContext,
    SecretUnavailable,
)
from psycopg.types.json import Jsonb
from reachy_hub.user_store import PostgresUserStore

from shared.database import SCHEMA_REVISION, check_schema
from shared.models.llm import LLMConfig, LLMConfigPatch

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_MIGRATION_TEST_URL"),
    reason="requires explicitly disposable Postgres",
)


@pytest.fixture
def database():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    dsn = psycopg.conninfo.make_conninfo(root, dbname=name)
    try:
        yield dsn
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                psycopg.sql.Identifier(name)))


@pytest.fixture
def keys():
    return Keyring("one", {"one": os.urandom(32)})


def seed_legacy(dsn):
    with psycopg.connect(dsn) as conn:
        conn.execute(BASELINE)
        for table, column in [
            ("sessions", "dnd"), ("sessions", "last_interruption_at"),
            ("audit_log", "action"), ("memories", "forgotten_at"),
            ("email_drafts", "dispatch_at"), ("llm_usage_log", "escalation_reason"),
        ]:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute("""INSERT INTO tasks VALUES ('task','preserved','pending',now(),NULL)""")
        conn.execute("""INSERT INTO sessions VALUES
            ('session','user','conversation','web','office','private',now(),now())""")
        config = LLMConfig.model_validate({
            "local": {"model": "fixture", "base_url": "http://localhost:9999/v1", "api_key": "local-secret"},
            "cloud": {"model": "fixture", "base_url": "https://example.org/v1", "api_key": "cloud-secret"},
            "routing": {"mode": "local_with_cloud_fallback"},
        })
        conn.execute("INSERT INTO llm_config (config) VALUES (%s)", (Jsonb(config.model_dump(mode="json")),))


def test_fresh_and_repeat(database, keys):
    upgrade(database, keys)
    upgrade(database, keys)

    async def check():
        store = await PostgresLLMSettingsStore.connect(database, keyring=keys)
        assert (await store.get()).local is None
        await store.close()
        users = await PostgresUserStore.connect(database)
        await users.bootstrap("fixture-owner", "fixture-password")
        await users.close()
        users = await PostgresUserStore.connect(database)
        assert await users.authenticate("fixture-owner", "fixture-password")
        await users.close()
    asyncio.run(check())


def test_legacy_atomic_migration_and_llm_semantics(database, keys):
    seed_legacy(database)
    with pytest.raises(RuntimeError, match="adopt-legacy"):
        upgrade(database, keys)
    upgrade(database, keys, adopt_legacy=True)
    upgrade(database, keys)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT text FROM tasks").fetchone() == ("preserved",)
        assert conn.execute("SELECT dnd,last_interruption_at FROM sessions").fetchone() == (False, None)
        config = conn.execute("SELECT config FROM llm_config").fetchone()[0]
        assert "api_key" not in str(config)
        assert "local-secret" not in str(config)
        assert conn.execute("SELECT count(*) FROM secrets").fetchone() == (2,)

    async def check():
        store = await PostgresLLMSettingsStore.connect(database, keyring=keys)
        config = await store.get()
        assert config.local.api_key == "local-secret"
        assert config.cloud.api_key == "cloud-secret"
        assert masked_config(config)["local"]["api_key"] == "********cret"
        config = await store.set(LLMConfigPatch(local={"model": "updated"}))
        assert config.local.api_key == "local-secret"
        config = await store.set(LLMConfigPatch(local={"api_key": None}))
        assert config.local.api_key is None
        config = await store.set(LLMConfigPatch(cloud={"api_key": "replacement"}))
        assert config.cloud.api_key == "replacement"
        await store.close()
        store = await PostgresLLMSettingsStore.connect(database, keyring=keys)
        assert (await store.get()).cloud.api_key == "replacement"
        await store.close()
    asyncio.run(check())
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM secrets").fetchone() == (1,)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""UPDATE llm_config SET config='{"local":{"api_key":"old-writer"}}'""")


@pytest.mark.parametrize("drift", [
    "ALTER TABLE tasks ADD COLUMN surprise TEXT",
    "ALTER TABLE tasks ALTER COLUMN text DROP NOT NULL",
    "ALTER TABLE tasks DROP COLUMN status",
    "CREATE TABLE surprise (id TEXT)",
    "ALTER TABLE tasks DROP CONSTRAINT tasks_pkey",
])
def test_drift_refuses_without_partial_repair(database, keys, drift):
    seed_legacy(database)
    with psycopg.connect(database) as conn:
        conn.execute(drift)
    with pytest.raises(RuntimeError):
        upgrade(database, keys, adopt_legacy=True)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT to_regclass('alembic_version')").fetchone() == (None,)
        assert conn.execute("SELECT config->'local'->>'api_key' FROM llm_config").fetchone() == ("local-secret",)


def test_lock_and_failure_recovery(database, keys, monkeypatch):
    seed_legacy(database)
    with psycopg.connect(database) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
        with pytest.raises(RuntimeError, match="Another migration"):
            upgrade(database, keys, adopt_legacy=True)
    original = Keyring.encrypt
    calls = 0

    def failing(self, *args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected failure")
        return original(self, *args)
    monkeypatch.setattr(Keyring, "encrypt", failing)
    with pytest.raises(RuntimeError, match="injected"):
        upgrade(database, keys, adopt_legacy=True)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT to_regclass('secrets')").fetchone() == (None,)
        assert conn.execute("SELECT to_regclass('alembic_version')").fetchone() == (None,)
    monkeypatch.setattr(Keyring, "encrypt", original)
    upgrade(database, keys, adopt_legacy=True)


def test_rotation_reuse_tampering_and_wrong_keys(database, keys):
    upgrade(database, keys)
    new_keys = Keyring("two", {**keys.keys, "two": os.urandom(32)})
    contexts = [SecretContext("owner", "google", "refresh_token"),
                SecretContext("owner", "smtp", "password")]
    refs = []

    async def check():
        old = PostgresSecretStore(keys)
        async with await psycopg.AsyncConnection.connect(database) as conn:
            for ctx in contexts:
                refs.append(await old.put(conn, ctx, "fixture-secret"))
        # One batch committed, then a simulated restart; old and new records coexist.
        new = PostgresSecretStore(new_keys)
        async with await psycopg.AsyncConnection.connect(database) as conn:
            assert await new.rotate_batch(conn, 1) == 1
        async with await psycopg.AsyncConnection.connect(database) as conn:
            assert await new.rotate_batch(conn, 1) == 1
            assert await new.rotate_batch(conn, 1) == 0
        async with await psycopg.AsyncConnection.connect(database) as conn:
            for ctx, ref in zip(contexts, refs, strict=True):
                assert await new.resolve(conn, ctx, ref) == "fixture-secret"
            with pytest.raises(SecretUnavailable):
                await new.resolve(conn, contexts[1], refs[0])
        wrong = PostgresSecretStore(Keyring("two", {"two": os.urandom(32)}))
        async with await psycopg.AsyncConnection.connect(database) as conn:
            with pytest.raises(SecretUnavailable):
                await wrong.resolve(conn, contexts[0], refs[0])
        async with await psycopg.AsyncConnection.connect(database) as conn:
            await conn.execute("UPDATE secrets SET ciphertext=%s WHERE id=%s", (b"tampered", refs[0]))
        async with await psycopg.AsyncConnection.connect(database) as conn:
            with pytest.raises(SecretUnavailable):
                await new.resolve(conn, contexts[0], refs[0])
    asyncio.run(check())
    with pytest.raises(SecretUnavailable):
        upgrade(database, new_keys)


def test_startup_revision_check(database, keys):
    async def check():
        async with await psycopg.AsyncConnection.connect(database) as conn:
            with pytest.raises(RuntimeError, match="unversioned"):
                await check_schema(conn)
    asyncio.run(check())
    upgrade(database, keys)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (SCHEMA_REVISION,)
        conn.execute("UPDATE alembic_version SET version_num='future'")
    async def incompatible():
        async with await psycopg.AsyncConnection.connect(database) as conn:
            with pytest.raises(RuntimeError, match="incompatible"):
                await check_schema(conn)
    asyncio.run(incompatible())


def test_backup_restore_old_and_rotated_keys(database, keys):
    import subprocess

    container = os.environ.get("DATABASE_MIGRATION_TEST_CONTAINER")
    if not container:
        pytest.skip("requires disposable Postgres container for pg_dump/pg_restore")
    name = psycopg.conninfo.conninfo_to_dict(database)["dbname"]
    seed_legacy(database)
    upgrade(database, keys, adopt_legacy=True)

    def dump():
        return subprocess.run(
            ["docker", "exec", container, "pg_dump", "-U", "fixture", "-Fc", name],
            check=True, capture_output=True,
        ).stdout

    def restore(backup):
        subprocess.run(
            ["docker", "exec", "-i", container, "pg_restore", "-U", "fixture",
             "--clean", "--if-exists", "--no-owner", "-d", name],
            input=backup, check=True, capture_output=True,
        )

    old_backup = dump()
    rotated = Keyring("two", {**keys.keys, "two": os.urandom(32)})

    async def rotate():
        async with await psycopg.AsyncConnection.connect(database) as conn:
            assert await PostgresSecretStore(rotated).rotate_batch(conn) == 2
    asyncio.run(rotate())
    new_backup = dump()
    new_only = Keyring("two", {"two": rotated.keys["two"]})
    restore(old_backup)
    upgrade(database, keys)
    with pytest.raises(SecretUnavailable):
        upgrade(database, new_only)
    restore(new_backup)
    upgrade(database, new_only)
    with pytest.raises(SecretUnavailable):
        upgrade(database, keys)


def test_partial_updates_serialize_and_smtp_resolves(database, keys, monkeypatch, tmp_path):
    import base64
    import json

    from companion_core.email.models import EmailDraft
    from companion_core.email.sender import smtp_send

    upgrade(database, keys)
    key_file = tmp_path / "keys.json"
    key_file.write_text(json.dumps({"active": keys.active, "keys": {
        key: base64.b64encode(value).decode() for key, value in keys.keys.items()
    }}))
    key_file.chmod(0o600)
    monkeypatch.setenv("SECRET_KEY_FILE", str(key_file))
    monkeypatch.setenv("DATABASE_URL", database)

    async def check():
        store = await PostgresLLMSettingsStore.connect(database, keyring=keys)
        await store.set(LLMConfigPatch(local={
            "base_url": "http://localhost:9999/v1", "model": "old", "api_key": "old",
        }))
        await asyncio.gather(
            store.set(LLMConfigPatch(local={"model": "new"})),
            store.set(LLMConfigPatch(local={"api_key": "new-key"})),
        )
        config = await store.get()
        assert config.local.model == "new"
        assert config.local.api_key == "new-key"
        await store.close()
        async with await psycopg.AsyncConnection.connect(database) as conn:
            ref = await PostgresSecretStore(keys).put(
                conn, SecretContext("owner", "smtp", "password"), "smtp-fixture",
            )
        monkeypatch.setenv("SMTP_SECRET_REF", ref)
        monkeypatch.setenv("SMTP_USERNAME", "fixture")
        monkeypatch.setenv("SMTP_PASSWORD", "must-not-override-reference")
        calls = []

        async def capture(*args, **kwargs):
            calls.append(kwargs)
        monkeypatch.setattr("companion_core.email.sender.aiosmtplib.send", capture)
        await smtp_send(EmailDraft(to="fixture@example.org", subject="fixture", body="fixture"))
        assert len(calls) == 1
        assert calls[0]["password"] == "smtp-fixture"
        assert calls[0]["username"] == "fixture"
        assert calls[0]["start_tls"] is True
        monkeypatch.setenv("SMTP_SECRET_REF", "missing")
        with pytest.raises(SecretUnavailable):
            await smtp_send(EmailDraft(to="fixture@example.org", subject="fixture", body="fixture"))
        assert len(calls) == 1
    asyncio.run(check())


def test_upgrade_requires_old_connections_stopped(database, keys):
    seed_legacy(database)
    with psycopg.connect(database) as conn:
        conn.execute("SELECT 1")
        with pytest.raises(RuntimeError, match="Stop hub/core"):
            upgrade(database, keys, adopt_legacy=True)
    upgrade(database, keys, adopt_legacy=True)
