"""ADR 0035 on real PostgreSQL (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector): migration 033 and its rollback script, the encrypted feed URL, and the real store
behind the real service across a restart. Synthetic data only."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from companion_core.calendar.feed import (
    CalendarFeedService,
    FeedConfig,
    FeedStatus,
    Snapshot,
)
from companion_core.calendar.feed_store import PostgresFeedStore
from companion_core.calendar.safe_fetch import FetchResult
from companion_core.migrations.__main__ import upgrade
from companion_core.secrets import Keyring, PostgresSecretStore, SecretContext

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
KEYS = Keyring("one", {"one": b"\x01" * 32})
OTHER_KEYS = Keyring("two", {"two": b"\x02" * 32})
ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-033.sql"
ROLLBACK_034 = ROLLBACK.with_name("rollback-034.sql")  # the head is 034 now: it is undone first
ROLLBACK_035 = ROLLBACK.with_name("rollback-035.sql")  # the head is 035 now (speaker identity): it is undone first
ROLLBACK_036 = ROLLBACK.with_name("rollback-036.sql")  # the head is 036 now (meeting email): it is undone first
FIXTURE = (Path(__file__).parent / "fixtures" / "calendar" / "work-calendar.ics").read_bytes()
URL = "https://calendar.example.com/private/abcdef-secret-token/basic.ics"
NOW = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)


@pytest.fixture
def dsn():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    url = psycopg.conninfo.make_conninfo(root, dbname=name)
    upgrade(url, KEYS)
    try:
        yield url
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def sql(dsn, query, params=None):
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


async def put(store, value, kind="url"):
    snapshot = Snapshot(facts=[], fetched_at=NOW, window_start=NOW, window_end=NOW, revision="r")
    await store.publish(value, snapshot, FeedStatus(host="calendar.example.com", source=kind, generation=1, digest="r"))


class Fetcher:
    async def check(self, url):
        return "calendar.example.com"

    async def fetch(self, url):
        return FetchResult(FIXTURE)


def with_store(dsn, body, keys=KEYS):
    async def go():
        store = await PostgresFeedStore.connect(dsn, PostgresSecretStore(keys))
        try:
            return await body(store)
        finally:
            await store.close()
    return asyncio.run(go())


def test_the_migration_adds_one_table_with_one_empty_row(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("036_meeting_email",)]
    assert sql(dsn, "SELECT id, secret_ref, snapshot FROM calendar_feed") == [("owner", None, None)]
    assert sql(dsn, "SELECT count(*) FROM pg_constraint WHERE conrelid = 'calendar_feed'::regclass AND contype = 'c'") == [(1,)]  # only the owner row can exist
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, "INSERT INTO calendar_feed (id) VALUES ('someone-else')")


def test_the_url_is_stored_encrypted_and_nowhere_in_plain_text(dsn):
    async def go(store):
        await put(store, URL)
        assert await store.get_url() == URL
    with_store(dsn, go)
    ref = sql(dsn, "SELECT secret_ref FROM calendar_feed")[0][0]
    assert ref and sql(dsn, "SELECT provider, purpose FROM secrets WHERE id = %s", (ref,)) == [("ics", "feed-url")]
    row = sql(dsn, "SELECT ciphertext, nonce FROM secrets WHERE id = %s", (ref,))[0]
    assert b"secret-token" not in bytes(row[0]) and b"calendar.example.com" not in bytes(row[0])
    table_text = str(sql(dsn, "SELECT config::text, overrides::text, coalesce(snapshot::text, ''), status::text, coalesce(secret_ref, '') FROM calendar_feed"))
    assert "secret-token" not in table_text and "abcdef" not in table_text
    assert "calendar.example.com" in table_text  # the host, shown to the owner, is the only part kept in the clear


def test_replacing_the_url_reuses_one_secret_row_and_clearing_deletes_it(dsn):
    async def go(store):
        await put(store, URL)
        await put(store, URL.replace("abcdef", "ghijkl"))
        assert (await store.get_url()).count("ghijkl") == 1
        assert sql(dsn, "SELECT count(*) FROM secrets WHERE provider = 'ics'") == [(1,)]
        await store.clear(5)
        assert await store.get_url() is None and (await store.load()).configured is False
    with_store(dsn, go)
    assert sql(dsn, "SELECT count(*) FROM secrets WHERE provider = 'ics'") == [(0,)]


def test_a_url_that_can_no_longer_be_decrypted_reads_as_unset_not_as_a_crash(dsn):
    with_store(dsn, lambda store: put(store, URL))
    async def go(store):
        assert await store.get_url() is None  # the key changed: the owner sets the URL again
        await put(store, URL)  # and that works
        assert await store.get_url() == URL
    with_store(dsn, go, keys=OTHER_KEYS)


def test_state_survives_a_restart_and_a_second_service_object(dsn):
    async def first():
        store = await PostgresFeedStore.connect(dsn, PostgresSecretStore(KEYS))
        service = CalendarFeedService(store, Fetcher(), clock=lambda: NOW)
        await service.set_config(FeedConfig(lead_minutes=7, device_horizon_hours=168, rules={"owner_emails": ["owner@example.com"]}))
        await service.set_url(URL)
        await service.refresh()
        await service.set_override("ics:" + "a" * 16 + ":0", "meeting")
        result = (await service.status(), await service.reminders(NOW))
        await store.close()
        return result
    before_status, before = asyncio.run(first())

    async def second():
        store = await PostgresFeedStore.connect(dsn, PostgresSecretStore(KEYS))
        service = CalendarFeedService(store, Fetcher(), clock=lambda: NOW)
        result = (await service.status(), await service.reminders(NOW), await store.get_url())
        await store.close()
        return result
    status, after, url = asyncio.run(second())
    assert url == URL and status == before_status and status["freshness"] == "fresh" and status["config"]["lead_minutes"] == 7
    assert after["reminders"] == before["reminders"] and len(after["reminders"]) >= 3 and after["snapshot_revision"] == before["snapshot_revision"]
    assert all(r["event_key"].startswith("ics:") for r in after["reminders"])


def test_the_rollback_script_removes_the_feed_and_its_secret_and_nothing_else(dsn):
    async def go(store):
        await put(store, URL)
        # another provider's secret must survive the rollback
        async with store._pool.connection() as conn:
            await PostgresSecretStore(KEYS).put(conn, SecretContext("owner", "google", "refresh-token"), "g-refresh-token")
    with_store(dsn, go)
    sql(dsn, "INSERT INTO calendar_events (id, title, start_at, end_at) VALUES ('e1', 'Local', now(), now())")
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK_036.read_text())
        conn.execute(ROLLBACK_035.read_text())
        conn.execute(ROLLBACK_034.read_text())
        conn.execute(ROLLBACK.read_text())  # one transaction, as the script's own instructions require
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("032_meeting_analysis",)]
    assert sql(dsn, "SELECT count(*) FROM pg_tables WHERE tablename = 'calendar_feed'") == [(0,)]
    assert sql(dsn, "SELECT provider FROM secrets") == [("google",)]
    assert sql(dsn, "SELECT count(*) FROM calendar_events") == [(1,)]
    upgrade(dsn, KEYS)  # applies again after a rollback
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("036_meeting_email",)] and sql(dsn, "SELECT id FROM calendar_feed") == [("owner",)]


def test_an_uploaded_file_is_stored_encrypted_and_survives_a_restart_with_the_same_revision(dsn):
    body = (FIXTURE).replace(b"SUMMARY:Design review", b"SUMMARY:Design review\nDESCRIPTION:confidential agenda text")

    async def first():
        store = await PostgresFeedStore.connect(dsn, PostgresSecretStore(KEYS))
        service = CalendarFeedService(store, Fetcher(), clock=lambda: NOW)
        await service.set_config(FeedConfig(device_horizon_hours=168, rules={"owner_emails": ["owner@example.com"]}))
        status = await service.upload(body, "/home/me/week.ics")
        again = await service.upload(body, "week.ics")
        assert again["generation"] == status["generation"]  # a repeated upload is not a new revision
        await store.close()
        return status

    status = asyncio.run(first())
    ref = sql(dsn, "SELECT secret_ref FROM calendar_feed")[0][0]
    cipher = bytes(sql(dsn, "SELECT ciphertext FROM secrets WHERE id = %s", (ref,))[0][0])
    assert b"confidential" not in cipher and b"Design review" not in cipher
    assert "confidential" not in str(sql(dsn, "SELECT config::text, coalesce(snapshot::text,''), status::text FROM calendar_feed"))  # a description is never kept in the clear either
    assert status["host"] == "week.ics" and status["source"] == "upload"

    async def second():
        store = await PostgresFeedStore.connect(dsn, PostgresSecretStore(KEYS))
        service = CalendarFeedService(store, Fetcher(), clock=lambda: NOW)
        before = await service.status()
        refreshed = await service.refresh()  # re-reads the stored file; the Fetcher is never asked
        await store.close()
        return before, refreshed
    before, refreshed = asyncio.run(second())
    assert before["generation"] == status["generation"] == refreshed["generation"] and refreshed["error"] is None and before["event_count"] > 15
