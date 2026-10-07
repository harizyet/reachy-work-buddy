"""Opt-in real Postgres check for meeting speaker names and corrections
(migration 019). DATABASE_MIGRATION_TEST_URL must point at a disposable server."""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.migrations.__main__ import upgrade
from companion_core.secrets import Keyring

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
    upgrade(dsn, Keyring("one", {"one": os.urandom(32)}))
    try:
        yield dsn
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def test_speaker_names_and_corrections_persist_and_default_empty(database, tmp_path):
    async def write() -> str:
        store = await PostgresMeetingStore.connect(database, audio_dir=tmp_path)
        try:
            meeting = await store.create_meeting(title="Sync", audio=b"x", source_filename="m.m4a", content_type="audio/mp4")
            assert meeting.speaker_names == {} and meeting.transcript_corrections == {}
            assert (await store.set_speaker_names(meeting.id, {"SPEAKER_00": "Ana"})).speaker_names == {"SPEAKER_00": "Ana"}
            await store.set_correction(meeting.id, 0, "We use Gemini.")
            await store.set_correction(meeting.id, 3, "Another.")
            assert (await store.set_correction(meeting.id, 3, None)).transcript_corrections == {"0": "We use Gemini."}
            assert (await store.set_corrections(meeting.id, {1: "a", 2: "b"})).transcript_corrections == {"0": "We use Gemini.", "1": "a", "2": "b"}
            assert await store.set_speaker_names("missing", {}) is None
            return meeting.id
        finally:
            await store.close()

    meeting_id = asyncio.run(write())

    async def read() -> None:
        store = await PostgresMeetingStore.connect(database, audio_dir=tmp_path)
        try:
            meeting = await store.get_meeting(meeting_id)
            assert meeting.speaker_names == {"SPEAKER_00": "Ana"}
            assert meeting.transcript_corrections == {"0": "We use Gemini.", "1": "a", "2": "b"}
        finally:
            await store.close()

    asyncio.run(read())


def test_key_terms_and_the_global_glossary_persist(database, tmp_path):
    async def run() -> None:
        store = await PostgresMeetingStore.connect(database, audio_dir=tmp_path)
        try:
            meeting = await store.create_meeting(title="Sync", audio=b"x", source_filename="m.m4a", content_type="audio/mp4")
            assert meeting.key_terms == []
            assert (await store.set_key_terms(meeting.id, ["Gemini", "Codex"])).key_terms == ["Gemini", "Codex"]
            await store.add_term("ClickHouse")
            await store.add_term("clickhouse")
            await store.add_term("Gemini")
            assert await store.list_terms() == ["ClickHouse", "Gemini"]
            assert await store.delete_term("GEMINI") is True and await store.delete_term("nope") is False
        finally:
            await store.close()
        store = await PostgresMeetingStore.connect(database, audio_dir=tmp_path)
        try:
            assert await store.list_terms() == ["ClickHouse"]
            assert (await store.get_meeting(meeting.id)).key_terms == ["Gemini", "Codex"]
        finally:
            await store.close()

    asyncio.run(run())


def test_outputs_persist_and_deleting_a_meeting_removes_the_record_and_its_audio(database, tmp_path):
    from companion_core.meetings.models import MeetingOutput

    async def run() -> None:
        store = await PostgresMeetingStore.connect(database, audio_dir=tmp_path)
        try:
            meeting = await store.create_meeting(title="Sync", audio=b"audio-bytes", source_filename="m.m4a", content_type="audio/mp4")
            assert meeting.summary is None and meeting.minutes is None
            await store.set_output(meeting.id, "summary", MeetingOutput(text="A summary", tier="local"))
            updated = await store.set_output(meeting.id, "minutes", MeetingOutput(text="Minutes", tier="deep"))
            assert updated.summary.text == "A summary" and updated.minutes.tier == "deep"
            assert (await store.set_output(meeting.id, "summary", None)).summary is None
            assert (tmp_path / meeting.id).is_dir()
            assert await store.delete_meeting(meeting.id) is True
            assert await store.delete_meeting(meeting.id) is False
            assert await store.get_meeting(meeting.id) is None
            assert not (tmp_path / meeting.id).exists()
            with __import__("pytest").raises(ValueError):
                await store.set_output("x", "poem", None)
        finally:
            await store.close()

    asyncio.run(run())
