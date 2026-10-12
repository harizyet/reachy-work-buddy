"""Hub-owned transcript archive. It never replays a turn into core."""
from typing import Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb

from shared.database import check_schema, open_pool
from shared.models.web_chat import ChatDetail, ChatDocumentRef, ChatRecord, ChatTurn


class ChatStore(Protocol):
    async def create(self, record: ChatRecord) -> ChatRecord: ...
    async def list(self, user_id: str) -> list[ChatRecord]: ...
    async def get(self, user_id: str, chat_id: str) -> ChatDetail | None: ...
    async def delete(self, user_id: str, chat_id: str) -> bool: ...
    async def append(self, chat_id: str, turn: ChatTurn) -> None: ...
    async def finish(self, chat_id: str, turn: ChatTurn) -> None: ...
    async def set_document(self, chat_id: str, document: ChatDocumentRef | None) -> None: ...


class InMemoryChatStore:
    def __init__(self):
        self.records: dict[str, ChatDetail] = {}
        self.documents: dict[str, ChatDocumentRef] = {}

    async def create(self, record):
        self.records[record.id] = ChatDetail(**record.model_dump())
        return record

    async def list(self, user_id):
        return [ChatRecord(**r.model_dump()) for r in sorted(
            self.records.values(), key=lambda r: r.updated_at, reverse=True
        ) if r.user_id == user_id]

    async def get(self, user_id, chat_id):
        record = self.records.get(chat_id)
        if not record or record.user_id != user_id:
            return None
        copy = record.model_copy(deep=True)
        copy.document = self.documents.get(chat_id)
        return copy

    async def set_document(self, chat_id, document):
        if document is None:
            self.documents.pop(chat_id, None)
        else:
            self.documents[chat_id] = document

    async def delete(self, user_id, chat_id):
        record = self.records.get(chat_id)
        if record is None or record.user_id != user_id:
            return False
        del self.records[chat_id]
        self.documents.pop(chat_id, None)
        return True

    async def append(self, chat_id, turn):
        self.records[chat_id].turns.append(turn.model_copy(deep=True))
        self.records[chat_id].updated_at = turn.created_at

    async def finish(self, chat_id, turn):
        turns = self.records[chat_id].turns
        for index, previous in enumerate(turns):
            if previous.id == turn.id:
                turns[index] = turn.model_copy(deep=True)
                break


class PostgresChatStore:
    def __init__(self, pool):
        self.pool = pool

    @classmethod
    async def connect(cls, dsn):
        pool = await open_pool(dsn)
        async with pool.connection() as conn:
            await check_schema(conn)
        return cls(pool)

    async def close(self):
        await self.pool.close()

    async def create(self, record):
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO web_chats (id, user_id, title, created_at, updated_at) VALUES (%s,%s,%s,%s,%s)',
                (record.id, record.user_id, record.title, record.created_at, record.updated_at),
            )
        return record

    async def list(self, user_id):
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                'SELECT id, user_id, title, created_at, updated_at FROM web_chats '
                'WHERE user_id = %s ORDER BY updated_at DESC, id', (user_id,),
            )
            return [self._record(row) for row in await cursor.fetchall()]

    @staticmethod
    def _record(row):
        return ChatRecord(id=row[0], user_id=row[1], title=row[2], created_at=row[3], updated_at=row[4])

    async def get(self, user_id, chat_id):
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                'SELECT id, user_id, title, created_at, updated_at FROM web_chats WHERE user_id=%s AND id=%s',
                (user_id, chat_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            cursor = await conn.execute(
                'SELECT data FROM web_chat_turns WHERE chat_id=%s ORDER BY sequence', (chat_id,),
            )
            turns, document = [], None
            for (data,) in await cursor.fetchall():
                if data.get("kind") == "attachment":  # a state entry in the same archive (no extra table): the last one is the current attachment; it is not a message
                    document = ChatDocumentRef.model_validate(data["document"]) if data.get("document") else None
                else:
                    turns.append(ChatTurn.model_validate(data))
            return ChatDetail(**self._record(row).model_dump(), turns=turns, document=document)

    async def delete(self, user_id, chat_id):
        # The turns go with the chat, in one transaction, and only for the owner's own chat.
        async with self.pool.connection() as conn, conn.transaction():
            cursor = await conn.execute('SELECT 1 FROM web_chats WHERE user_id=%s AND id=%s FOR UPDATE', (user_id, chat_id))
            if await cursor.fetchone() is None:
                return False
            await conn.execute('DELETE FROM web_chat_turns WHERE chat_id=%s', (chat_id,))
            await conn.execute('DELETE FROM web_chats WHERE id=%s', (chat_id,))
            return True

    async def append(self, chat_id, turn):
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO web_chat_turns (id, chat_id, data) VALUES (%s,%s,%s)',
                (turn.id, chat_id, Jsonb(turn.model_dump(mode='json'))),
            )
            await conn.execute('UPDATE web_chats SET updated_at=%s WHERE id=%s', (turn.created_at, chat_id))

    async def finish(self, chat_id, turn):
        async with self.pool.connection() as conn:
            await conn.execute('UPDATE web_chat_turns SET data=%s WHERE id=%s AND chat_id=%s',
                               (Jsonb(turn.model_dump(mode='json')), turn.id, chat_id))

    async def set_document(self, chat_id, document):
        """Record the conversation's attachment (or its removal) as a state entry in the chat's own archive. It does not touch the chat's updated time and is never shown as a message."""
        entry = {"id": str(uuid4()), "kind": "attachment", "document": document.model_dump(mode="json", exclude={"available"}) if document else None}
        async with self.pool.connection() as conn:
            await conn.execute("INSERT INTO web_chat_turns (id, chat_id, data) VALUES (%s,%s,%s)", (entry["id"], chat_id, Jsonb(entry)))
