"""Phase 54, opt-in real Postgres: migration 035, persistence of speaker identities, supersede on a different diarization, and deletion.
DATABASE_MIGRATION_TEST_URL must point at a disposable server."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from companion_core.meetings import speaker_identity
from companion_core.meetings.models import (
    MeetingJobStatus,
    MeetingOutput,
    speaker_basis,
)
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.migrations.__main__ import upgrade
from companion_core.secrets import Keyring

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres")

ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-035.sql"
KEYS = Keyring("one", {"one": os.urandom(32)})
DIAR = [{"start": 0, "end": 30, "speaker": "SPEAKER_00"}, {"start": 30, "end": 60, "speaker": "SPEAKER_01"}]


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


async def seeded(store):
    meeting = await store.create_meeting(title="Sync", audio=b"x", source_filename="m.m4a", content_type="audio/mp4")
    sql(store_dsn(store), "UPDATE meetings SET status = 'complete', diarization_segments = %s::jsonb, transcript_segments = '[]'::jsonb WHERE id = %s", (__import__("json").dumps(DIAR), meeting.id))
    return meeting.id


def store_dsn(store):
    return store._dsn


def test_the_migration_adds_one_nullable_column_and_is_repeatable(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("035_meeting_speaker_identity",)]
    assert sql(dsn, "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'meetings' AND column_name = 'speaker_identity'") == [("YES",)]
    upgrade(dsn, KEYS)


def test_identities_persist_across_a_reconnect_and_a_legacy_row_reads_as_empty(dsn, tmp_path):
    async def write():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        store._dsn = dsn
        try:
            meeting_id = await seeded(store)
            sql(dsn, "UPDATE meetings SET speaker_identity = NULL WHERE id = %s", (meeting_id,))
            legacy = await store.get_meeting(meeting_id)
            assert legacy.speaker_identity.identities == {} and legacy.stale_outputs == []
            state, names = speaker_identity.apply(legacy, {"SPEAKER_00": {"status": "named", "name": "Priya", "contact_id": "c1"}, "SPEAKER_01": {"status": "unknown"}})
            saved = await store.set_speaker_identity(meeting_id, state, names)
            assert saved.speaker_names == {"SPEAKER_00": "Priya"}
            await store.set_output(meeting_id, "summary", MeetingOutput(text="s", tier="local", speaker_basis=speaker_basis(names)))
            return meeting_id
        finally:
            await store.close()

    meeting_id = asyncio.run(write())

    async def read():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        try:
            meeting = await store.get_meeting(meeting_id)
            assert meeting.speaker_names == {"SPEAKER_00": "Priya"} and meeting.speaker_identity.identities["SPEAKER_00"].contact_id == "c1"
            assert meeting.speaker_identity.identities["SPEAKER_01"].status == "unknown" and meeting.speaker_identity.fingerprint
            assert meeting.diarization_segments == DIAR and meeting.stale_outputs == []
            assert await store.set_speaker_identity("missing", meeting.speaker_identity, {}) is None
        finally:
            await store.close()

    asyncio.run(read())


def test_a_different_diarization_supersedes_names_and_an_identical_one_keeps_them(dsn, tmp_path):
    async def go():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        store._dsn = dsn
        try:
            meeting_id = await seeded(store)
            meeting = await store.get_meeting(meeting_id)
            state, names = speaker_identity.apply(meeting, {"SPEAKER_00": {"status": "named", "name": "Priya"}})
            await store.set_speaker_identity(meeting_id, state, names)

            sql(dsn, "UPDATE meetings SET status = %s WHERE id = %s", (MeetingJobStatus.DIARIZING.value, meeting_id))
            same = await store.mark_diarized(meeting_id, diarization_segments=[dict(s) for s in DIAR])
            assert same.speaker_names == {"SPEAKER_00": "Priya"} and same.speaker_identity.superseded is None

            sql(dsn, "UPDATE meetings SET status = %s WHERE id = %s", (MeetingJobStatus.DIARIZING.value, meeting_id))
            moved = await store.mark_diarized(meeting_id, diarization_segments=[{"start": 0, "end": 10, "speaker": "SPEAKER_00"}, {"start": 10, "end": 60, "speaker": "SPEAKER_01"}])
            assert moved.speaker_names == {} and moved.speaker_identity.identities == {}
            assert moved.speaker_identity.superseded.identities["SPEAKER_00"].name == "Priya"
            assert (await store.get_meeting(meeting_id)).speaker_identity.superseded.identities["SPEAKER_00"].name == "Priya"  # and it was persisted
        finally:
            await store.close()

    asyncio.run(go())


def test_deleting_the_meeting_removes_the_mapping(dsn, tmp_path):
    async def go():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        store._dsn = dsn
        try:
            meeting_id = await seeded(store)
            meeting = await store.get_meeting(meeting_id)
            state, names = speaker_identity.apply(meeting, {"SPEAKER_00": {"status": "named", "name": "Priya"}})
            await store.set_speaker_identity(meeting_id, state, names)
            assert await store.delete_meeting(meeting_id)
            assert sql(dsn, "SELECT count(*) FROM meetings WHERE id = %s", (meeting_id,)) == [(0,)]
            assert sql(dsn, "SELECT count(*) FROM meetings WHERE speaker_identity::text LIKE '%%Priya%%' OR speaker_names::text LIKE '%%Priya%%'", ()) == [(0,)]
        finally:
            await store.close()

    asyncio.run(go())


def test_the_rollback_script_removes_only_the_column_and_names_survive(dsn, tmp_path):
    async def seed():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        store._dsn = dsn
        try:
            meeting_id = await seeded(store)
            await store.set_speaker_names(meeting_id, {"SPEAKER_00": "Priya"})
            return meeting_id
        finally:
            await store.close()

    meeting_id = asyncio.run(seed())
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK.read_text())
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("034_meeting_multimodal",)]
    assert sql(dsn, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'meetings' AND column_name = 'speaker_identity'") == [(0,)]
    assert sql(dsn, "SELECT speaker_names FROM meetings WHERE id = %s", (meeting_id,)) == [({"SPEAKER_00": "Priya"},)]
    upgrade(dsn, KEYS)
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("035_meeting_speaker_identity",)]
