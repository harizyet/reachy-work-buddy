"""ADR 0040, opt-in real PostgreSQL: migration 037 and its rollback, the append-only processing record written in the same statement as the step it describes, and the owner's name on the
dedicated sender. DATABASE_MIGRATION_TEST_URL must point at a disposable server."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from companion_core.email.sender_config import PostgresMailSenderStore, SenderSettings
from companion_core.meetings import provenance
from companion_core.meetings.models import MeetingJobStatus, MeetingOutput
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.migrations.__main__ import upgrade
from companion_core.secrets import Keyring

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres")

ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-037.sql"
ROLLBACK_038 = ROLLBACK.with_name("rollback-038.sql")  # the head is 038 now (voice profiles): it is undone first
KEYS = Keyring("one", {"one": os.urandom(32)})


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


def test_the_migration_adds_an_empty_record_to_existing_meetings_and_is_repeatable(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("038_voice_profiles",)]
    assert sql(dsn, "SELECT column_name FROM information_schema.columns WHERE table_name = 'meetings' AND column_name = 'processing_events'") == [("processing_events",)]
    assert sql(dsn, "SELECT column_name FROM information_schema.columns WHERE table_name = 'mail_sender' AND column_name = 'owner_name'") == [("owner_name",)]
    upgrade(dsn, KEYS)


def test_a_meeting_that_existed_before_the_migration_reads_back_with_no_record_and_is_therefore_never_local(dsn, tmp_path):
    async def go():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        try:
            meeting = await store.create_meeting(title="Old", audio=b"x", source_filename="a.wav", content_type="audio/wav")
            return await store.get_meeting(meeting.id)
        finally:
            await store.close()

    meeting = asyncio.run(go())
    assert meeting.processing_events == [] and provenance.assess(meeting).status == "unverified"


def test_every_step_writes_its_event_in_the_same_statement_and_events_are_only_ever_appended(dsn, tmp_path):
    async def go():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        try:
            meeting = await store.create_meeting(title="Weekly", audio=b"x", source_filename="a.wav", content_type="audio/wav")
            sql(dsn, "UPDATE meetings SET status = %s WHERE id = %s", (MeetingJobStatus.TRANSCRIBING.value, meeting.id))
            await store.mark_transcribed(meeting.id, transcript_segments=[{"start": 0, "end": 1, "text": "hi"}], processing=provenance.event("transcription", "local"))
            await store.mark_diarized(meeting.id, diarization_segments=[{"start": 0, "end": 1, "speaker": "SPEAKER_00"}], processing=provenance.event("diarization", "local"))
            await store.mark_aligned(meeting.id, aligned_segments=[{"speaker": "SPEAKER_00"}], processing=provenance.event("speaker_processing", "local"))
            first = MeetingOutput(text="cloud summary", tier="cloud", location="external")
            await store.record_processing(meeting.id, provenance.event("summary", "external"))
            await store.set_output(meeting.id, "summary", first)
            second = MeetingOutput(text="local summary", tier="local", location="local", generated_at=datetime(2030, 1, 1, tzinfo=UTC))
            await store.set_output(meeting.id, "summary", second)
            await store.set_output(meeting.id, "minutes", MeetingOutput(text="m", tier="local", location="local"))
            await store.set_output(meeting.id, "summary", None)  # clearing removes nothing from the record
            await store.set_title(meeting.id, title="Release", description="d", source="generated", processing=provenance.event("title", "local"))
            return await store.get_meeting(meeting.id)
        finally:
            await store.close()

    meeting = asyncio.run(go())
    steps = [(e.step, e.location) for e in meeting.processing_events]
    assert steps == [("transcription", "local"), ("diarization", "local"), ("speaker_processing", "local"), ("summary", "external"), ("summary", "external"), ("summary", "local"),
                     ("minutes", "local"), ("title", "local")]
    assert meeting.processing_events[5].subject == datetime(2030, 1, 1, tzinfo=UTC).isoformat()
    verdict = provenance.assess(meeting)
    assert verdict.status == "external" and verdict.external_steps == ["summary"]  # the cleared and replaced summaries cannot hide the cloud one


def test_an_output_without_a_recorded_location_leaves_no_event(dsn, tmp_path):
    async def go():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        try:
            meeting = await store.create_meeting(title="Old", audio=b"x", source_filename="a.wav", content_type="audio/wav")
            await store.set_output(meeting.id, "summary", MeetingOutput(text="old", tier="local"))
            return await store.get_meeting(meeting.id)
        finally:
            await store.close()

    assert asyncio.run(go()).processing_events == []


def test_the_sender_keeps_the_owner_name_and_changing_it_does_not_switch_sending_off(dsn):
    async def go():
        store = await PostgresMailSenderStore.connect(dsn, keyring=KEYS)
        try:
            await store.save(SenderSettings(host="smtp.example.test", from_address="a@example.test", username="a@example.test", owner_name="  Hariz  "), password="pw")
            await store.record_verification(True, "ok")
            await store.set_enabled(True)
            saved = await store.save(SenderSettings(host="smtp.example.test", from_address="a@example.test", username="a@example.test", owner_name="Hariz Yet"), password=None)
            return saved, await store.get()
        finally:
            await store.close()

    saved, got = asyncio.run(go())
    assert saved.owner_name == got.owner_name == "Hariz Yet" and got.enabled is True


def test_the_rollback_script_drops_both_columns_keeps_meetings_and_the_migration_applies_again(dsn, tmp_path):
    async def seed():
        store = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        try:
            meeting = await store.create_meeting(title="Keep me", audio=b"x", source_filename="a.wav", content_type="audio/wav")
            await store.record_processing(meeting.id, provenance.event("summary", "external"))
            return meeting.id
        finally:
            await store.close()

    meeting_id = asyncio.run(seed())
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK_038.read_text())
        conn.execute(ROLLBACK.read_text())  # one transaction, as the script's own instructions require
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("036_meeting_email",)]
    assert sql(dsn, "SELECT count(*) FROM information_schema.columns WHERE (table_name, column_name) IN (('meetings','processing_events'),('mail_sender','owner_name'))") == [(0,)]
    assert sql(dsn, "SELECT title FROM meetings WHERE id = %s", (meeting_id,)) == [("Keep me",)]
    upgrade(dsn, KEYS)
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("038_voice_profiles",)]
    assert sql(dsn, "SELECT processing_events FROM meetings WHERE id = %s", (meeting_id,)) == [([],)]  # the dropped record is not resurrected
