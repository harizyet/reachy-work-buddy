"""Phase 55, opt-in real PostgreSQL: migration 036 and its rollback, the email store's atomic claim and guarded transitions, and the dedicated sender's credential in the encrypted SecretStore.
DATABASE_MIGRATION_TEST_URL must point at a disposable server."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from companion_core.email.models import (
    MEETING_MINUTES_KIND,
    DraftStatus,
    EmailDraft,
    Recipients,
)
from companion_core.email.postgres_store import PostgresEmailStore
from companion_core.email.sender_config import (
    PostgresMailSenderStore,
    SenderConfigError,
    SenderSettings,
)
from companion_core.email.workflow import dispatch_due_drafts, recover_interrupted
from companion_core.meeting_distribution.groups import GroupError, PostgresGroupStore
from companion_core.migrations.__main__ import upgrade
from companion_core.secrets import Keyring

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres")

ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-036.sql"
KEYS = Keyring("one", {"one": os.urandom(32)})
SENDER = "reachy.minutes@example.test"
PDF = b"%PDF-1.4 fixture \x00\x01 bytes"


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


def sql(url, query, args=()):
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.execute(query, args)
        return cur.fetchall() if cur.description else None


def package(**over) -> EmailDraft:
    base = {"to": "a@example.org", "subject": "Meeting minutes: Weekly sync", "body": "Hello\n\nMinutes\n", "kind": MEETING_MINUTES_KIND, "sender": SENDER, "status": DraftStatus.READY_FOR_REVIEW,
            "recipients": Recipients(to=["a@example.org"], cc=["b@example.org"], bcc=["c@example.org"]), "source": {"meeting_id": "m1", "summary_at": "2026-10-14T00:00:00+00:00"}}
    base.update(over)
    return EmailDraft(**base)


async def queued(store: PostgresEmailStore, **over) -> EmailDraft:
    saved = await store.create_package(package(**over), [("m.pdf", "application/pdf", PDF)])
    await store.approve_reviewed(saved.id, package_hash=saved.package_hash, message_id=f"<{saved.id}@example.test>")
    return await store.queue_draft(saved.id, dispatch_at=datetime.now(UTC) - timedelta(seconds=1))


# ---- migration 036 -------------------------------------------------------------------------------------------------------------------------------

def test_the_migration_adds_columns_and_tables_without_touching_existing_drafts_and_is_repeatable(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("036_meeting_email",)]
    cols = {r[0] for r in sql(dsn, "SELECT column_name FROM information_schema.columns WHERE table_name = 'email_drafts'")}
    assert {"kind", "recipients", "source", "package_hash", "approved_hash", "message_id", "sender", "attempts", "claimed_at", "last_error", "provider_response"} <= cols
    tables = {r[0] for r in sql(dsn, "SELECT tablename FROM pg_tables")}
    assert {"email_draft_attachments", "email_draft_events", "mail_sender", "meeting_recipient_groups"} <= tables
    upgrade(dsn, KEYS)  # a repeat changes nothing


def test_an_existing_text_draft_survives_the_upgrade_with_its_defaults(dsn):
    async def go():
        store = await PostgresEmailStore.connect(dsn)
        try:
            draft = await store.create_draft(to="bob@example.org", subject="Hi", body="Hello")
            got = await store.get_draft(draft.id)
            assert got.kind == "text" and got.recipients is None and got.attachments == [] and got.attempts == 0 and got.package_hash is None
            assert (await store.approve_draft(draft.id)).status == DraftStatus.APPROVED
            assert (await store.queue_draft(draft.id, dispatch_at=datetime.now(UTC))).status == DraftStatus.QUEUED  # NULL hashes are equal: the older flow is unchanged
        finally:
            await store.close()

    asyncio.run(go())


def test_the_rollback_script_removes_meeting_drafts_and_the_credential_but_keeps_plain_drafts_and_the_migration_applies_again(dsn):
    async def seed():
        store = await PostgresEmailStore.connect(dsn)
        senders = await PostgresMailSenderStore.connect(dsn, keyring=KEYS)
        try:
            await senders.save(SenderSettings(host="smtp.example.test", from_address=SENDER, username=SENDER), password="rollback-me")
            keep = await store.create_draft(to="bob@example.org", subject="Keep", body="plain")
            gone = await queued(store)
            return keep.id, gone.id
        finally:
            await store.close()
            await senders.close()

    keep, gone = asyncio.run(seed())
    assert sql(dsn, "SELECT count(*) FROM secrets WHERE provider = 'mail-sender'") == [(1,)]
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK.read_text())  # one transaction, as the script's own instructions require
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("035_meeting_speaker_identity",)]
    assert sql(dsn, "SELECT id FROM email_drafts ORDER BY id") == [(keep,)]  # the queued meeting package is gone: it can never be sent as a plain draft
    assert sql(dsn, "SELECT count(*) FROM secrets WHERE provider = 'mail-sender'") == [(0,)]
    assert sql(dsn, "SELECT count(*) FROM pg_tables WHERE tablename IN ('mail_sender','email_draft_events','email_draft_attachments','meeting_recipient_groups')") == [(0,)]
    assert gone not in [r[0] for r in sql(dsn, "SELECT id FROM email_drafts")]
    upgrade(dsn, KEYS)
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("036_meeting_email",)]


# ---- the store -----------------------------------------------------------------------------------------------------------------------------------

def test_a_package_round_trips_with_its_attachment_hash_and_review_binding(dsn):
    async def go():
        store = await PostgresEmailStore.connect(dsn)
        try:
            saved = await store.create_package(package(), [("m.pdf", "application/pdf", PDF)])
            got = await store.get_draft(saved.id)
            assert got.kind == MEETING_MINUTES_KIND and got.status == DraftStatus.READY_FOR_REVIEW and got.recipients.bcc == ["c@example.org"]
            assert [(a.name, a.size) for a in got.attachments] == [("m.pdf", len(PDF))] and got.attachments[0].sha256 == saved.attachments[0].sha256
            assert await store.get_blobs(saved.id) == [("m.pdf", "application/pdf", PDF)]
            assert await store.approve_reviewed(saved.id, package_hash="0" * 64, message_id="<x@t>") is None  # a stale hash never approves
            approved = await store.approve_reviewed(saved.id, package_hash=got.package_hash, message_id="<x@t>")
            assert approved.status == DraftStatus.APPROVED and approved.approved_hash == approved.package_hash
            assert await store.approve_reviewed(saved.id, package_hash=got.package_hash, message_id="<y@t>") is None  # a duplicate approval does nothing
            # an edit returns it to review with a new hash and drops the approval
            edited = await store.update_package(saved.id, recipients=Recipients(to=["z@example.org"]), subject="New", body="New body", sender=SENDER, blobs=[])
            assert edited.status == DraftStatus.READY_FOR_REVIEW and edited.approved_hash is None and edited.package_hash != got.package_hash and edited.attachments == []
            assert await store.get_blobs(saved.id) == [] and (await store.get_draft(saved.id)).recipients.to == ["z@example.org"]
            assert await store.queue_draft(saved.id, dispatch_at=datetime.now(UTC)) is None  # not approved
        finally:
            await store.close()

    asyncio.run(go())


def test_the_database_refuses_to_queue_or_claim_a_package_whose_approval_no_longer_matches(dsn):
    async def go():
        store = await PostgresEmailStore.connect(dsn)
        try:
            draft = await queued(store)
            sql(dsn, "UPDATE email_drafts SET body = 'edited behind the back' , package_hash = 'other' WHERE id = %s", (draft.id,))  # a row changed outside the owner's review
            assert await store.claim_due(datetime.now(UTC) + timedelta(minutes=1)) is None
            sql(dsn, "UPDATE email_drafts SET status = 'approved', dispatch_at = NULL WHERE id = %s", (draft.id,))
            assert await store.queue_draft(draft.id, dispatch_at=datetime.now(UTC)) is None
        finally:
            await store.close()

    asyncio.run(go())


def test_concurrent_workers_claim_a_draft_exactly_once_and_distinct_drafts_to_distinct_workers(dsn):
    async def go():
        store = await PostgresEmailStore.connect(dsn)
        try:
            one = await queued(store)
            now = datetime.now(UTC) + timedelta(minutes=1)
            claims = await asyncio.gather(*(store.claim_due(now) for _ in range(8)))
            winners = [c for c in claims if c is not None]
            assert len(winners) == 1 and winners[0].id == one.id and winners[0].status == DraftStatus.SENDING and winners[0].attempts == 1
            drafts = [await queued(store) for _ in range(3)]
            claims = await asyncio.gather(*(store.claim_due(now) for _ in range(6)))
            got = [c.id for c in claims if c is not None]
            assert sorted(got) == sorted(d.id for d in drafts) and len(set(got)) == 3  # SKIP LOCKED: each draft to one worker
        finally:
            await store.close()

    asyncio.run(go())


def test_concurrent_dispatch_passes_send_each_message_once(dsn):
    async def go():
        store = await PostgresEmailStore.connect(dsn)
        sent = []

        async def send(draft):
            await asyncio.sleep(0.05)
            sent.append(draft.id)
            return "250 ok"

        try:
            made = [await queued(store) for _ in range(3)]
            now = datetime.now(UTC) + timedelta(minutes=1)
            totals = await asyncio.gather(*(dispatch_due_drafts(store, send_fn=send, now=now) for _ in range(4)))
            assert sum(totals) == 3 and sorted(sent) == sorted(d.id for d in made)
            assert {(await store.get_draft(d.id)).status for d in made} == {DraftStatus.SENT}
            assert (await store.get_draft(made[0].id)).provider_response == "250 ok"
        finally:
            await store.close()

    asyncio.run(go())


def test_outcomes_are_guarded_by_state_and_an_interrupted_send_becomes_unknown_and_stays_in_the_event_history(dsn):
    async def go():
        store = await PostgresEmailStore.connect(dsn)
        try:
            draft = await queued(store)
            assert await store.mark_failed(draft.id, error="x") is None  # only a SENDING draft can fail
            assert await store.requeue_for_retry(draft.id, dispatch_at=datetime.now(UTC), error="x") is None  # nor be rescheduled
            claimed = await store.claim_due(datetime.now(UTC) + timedelta(minutes=1))
            assert claimed.status == DraftStatus.SENDING
            assert await recover_interrupted(store, older_than_seconds=300) == 0  # claimed just now: a slow send is left alone
            assert await recover_interrupted(store, older_than_seconds=None) == 1  # a restart settles every SENDING row
            got = await store.get_draft(draft.id)
            assert got.status == DraftStatus.UNKNOWN_DELIVERY and "stopped" in got.last_error and got.claimed_at is None
            assert [e.event for e in await store.list_events(draft.id)] == ["unknown_delivery"]
            assert (await store.resolve_unknown(draft.id, delivered=False)).status == DraftStatus.READY_FOR_REVIEW
            assert await store.resolve_unknown(draft.id, delivered=True) is None
            assert (await store.discard_draft(draft.id)).status == DraftStatus.CANCELLED
            assert await store.discard_draft(draft.id) is None
        finally:
            await store.close()

    asyncio.run(go())


def test_deleting_a_draft_removes_its_attachments_and_events(dsn):
    async def go():
        store = await PostgresEmailStore.connect(dsn)
        try:
            draft = await queued(store)
            await store.add_event(draft.id, "queued", {"n": 1})
        finally:
            await store.close()
        return draft.id

    draft_id = asyncio.run(go())
    sql(dsn, "DELETE FROM email_drafts WHERE id = %s", (draft_id,))
    assert sql(dsn, "SELECT count(*) FROM email_draft_attachments WHERE draft_id = %s", (draft_id,)) == [(0,)]
    assert sql(dsn, "SELECT count(*) FROM email_draft_events WHERE draft_id = %s", (draft_id,)) == [(0,)]


# ---- the dedicated sender and its credential ---------------------------------------------------------------------------------------------------

def test_the_credential_is_encrypted_in_the_secret_store_and_never_in_the_settings_row_or_a_dump(dsn):
    async def go():
        senders = await PostgresMailSenderStore.connect(dsn, keyring=KEYS)
        try:
            assert (await senders.get()).enabled is False and (await senders.get()).configured is False  # off and empty by default
            saved = await senders.save(SenderSettings(host="smtp.example.test", from_address=SENDER, username=SENDER), password="PLAINTEXT-APP-PASSWORD-123")
            assert saved.secret_ref and saved.enabled is False and "PLAINTEXT" not in str(saved.view())
            assert await senders.password() == "PLAINTEXT-APP-PASSWORD-123"
            with pytest.raises(SenderConfigError, match="verify"):
                await senders.set_enabled(True)
            await senders.record_verification(True, "connected")
            assert (await senders.set_enabled(True)).enabled is True
            return saved.secret_ref
        finally:
            await senders.close()

    ref = asyncio.run(go())
    row = sql(dsn, "SELECT * FROM mail_sender WHERE id = 1")
    assert "PLAINTEXT-APP-PASSWORD-123" not in str(row)  # the settings row holds only the opaque reference
    cipher = sql(dsn, "SELECT ciphertext, owner, provider, purpose FROM secrets WHERE id = %s", (ref,))[0]
    assert b"PLAINTEXT-APP-PASSWORD-123" not in bytes(cipher[0]) and cipher[1:] == ("owner", "mail-sender", "password")
    with psycopg.connect(dsn) as conn:  # a dump of the database (a backup) carries only ciphertext
        text = "".join(str(r) for r in conn.execute("SELECT * FROM secrets").fetchall()) + str(conn.execute("SELECT * FROM mail_sender").fetchall())
    assert "PLAINTEXT-APP-PASSWORD-123" not in text


def test_rotation_replaces_the_credential_in_place_and_switches_sending_off_and_disconnect_deletes_it(dsn):
    async def go():
        senders = await PostgresMailSenderStore.connect(dsn, keyring=KEYS)
        try:
            first = await senders.save(SenderSettings(host="smtp.example.test", from_address=SENDER, username=SENDER), password="old-password")
            await senders.record_verification(True, "ok")
            await senders.set_enabled(True)
            rotated = await senders.save(SenderSettings(host="smtp.example.test", from_address=SENDER, username=SENDER), password="new-password")
            assert rotated.secret_ref == first.secret_ref and rotated.enabled is False and rotated.verified_ok is None  # same reference, new value, must be verified and enabled again
            assert await senders.password() == "new-password"
            assert sql(dsn, "SELECT count(*) FROM secrets WHERE provider = 'mail-sender'") == [(1,)]
            kept = await senders.save(SenderSettings(host="smtp.example.test", from_address=SENDER, username=SENDER), password=None)
            assert kept.secret_ref == first.secret_ref and await senders.password() == "new-password"
            gone = await senders.disconnect()
            assert gone.configured is False and gone.secret_ref is None and gone.enabled is False
            assert sql(dsn, "SELECT count(*) FROM secrets WHERE provider = 'mail-sender'") == [(0,)]
            assert await senders.password() is None
            with pytest.raises(SenderConfigError, match="STARTTLS"):
                await senders.save(SenderSettings(host="smtp.example.test", from_address=SENDER, username=SENDER, security="none"), password="x")
        finally:
            await senders.close()

    asyncio.run(go())


def test_recipient_groups_are_unique_validated_and_persistent(dsn):
    async def go():
        groups = await PostgresGroupStore.connect(dsn)
        try:
            g = await groups.save("Project team", ["B@Example.org", "a@example.org", "b@example.org"])
            assert g.addresses == ["b@example.org", "a@example.org"]
            with pytest.raises(GroupError, match="already exists"):
                await groups.save("project TEAM", ["x@example.org"])
            with pytest.raises(GroupError):
                await groups.save("Bad", ["nope"])
            assert (await groups.save("Renamed", ["c@example.org"], g.id)).name == "Renamed" and [x.name for x in await groups.list()] == ["Renamed"]
            assert await groups.save("x", ["c@example.org"], "missing") is None and await groups.delete(g.id) and not await groups.delete(g.id)
        finally:
            await groups.close()

    asyncio.run(go())
