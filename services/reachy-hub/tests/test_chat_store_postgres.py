"""The chat archive's delete against a real Postgres: the turns go with the chat, and only for the owner's own chat."""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from reachy_hub.chat_store import PostgresChatStore

from shared.models.web_chat import ChatRecord, ChatTurn

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="needs a disposable Postgres")


@pytest.fixture
def database():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "chat_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    dsn = psycopg.conninfo.make_conninfo(root, dbname=name)
    with psycopg.connect(dsn, autocommit=True) as conn:  # the same two tables as migration 012
        conn.execute("CREATE TABLE web_chats (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)")
        conn.execute("CREATE TABLE web_chat_turns (sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, chat_id TEXT NOT NULL REFERENCES web_chats(id), data JSONB NOT NULL)")
    try:
        yield dsn
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def test_delete_removes_the_chat_and_its_turns_for_the_owner_only(database):
    async def run() -> None:
        pool = AsyncConnectionPool(database, open=False)
        await pool.open()
        store = PostgresChatStore(pool)
        try:
            mine = await store.create(ChatRecord(user_id="owner", title="Mine"))
            other = await store.create(ChatRecord(user_id="someone", title="Theirs"))
            for chat in (mine, other):
                await store.append(chat.id, ChatTurn(text="hello"))
            assert await store.delete("owner", other.id) is False                  # not the owner's chat
            assert await store.delete("owner", mine.id) is True
            assert await store.delete("owner", mine.id) is False
            assert await store.get("owner", mine.id) is None and await store.list("owner") == []
            assert (await store.get("someone", other.id)).turns[0].text == "hello"   # the other chat is untouched
            async with pool.connection() as conn:
                cursor = await conn.execute("SELECT count(*) FROM web_chat_turns WHERE chat_id = %s", (mine.id,))
                assert (await cursor.fetchone())[0] == 0
        finally:
            await pool.close()

    asyncio.run(run())
