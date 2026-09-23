"""Postgres-backed EmailStore. See store.py for the interface and the
approval-gate/delayed-queue note in models.py/workflow.py."""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg_pool import AsyncConnectionPool

from companion_core.email.models import DraftStatus, EmailDraft, EmailMessage
from shared.database import check_schema

_RECEIVED_COLUMNS = "id, sender, subject, body, received_at"
_DRAFT_COLUMNS = '"to", subject, body, in_reply_to, status, created_at, approved_at, dispatch_at, sent_at'
_DRAFT_COLUMNS_WITH_ID = f"id, {_DRAFT_COLUMNS}"


def _received_from_row(row: tuple) -> EmailMessage:
    return EmailMessage(id=row[0], sender=row[1], subject=row[2], body=row[3], received_at=row[4])


def _draft_from_row(row: tuple) -> EmailDraft:
    return EmailDraft(
        id=row[0],
        to=row[1],
        subject=row[2],
        body=row[3],
        in_reply_to=row[4],
        status=DraftStatus(row[5]),
        created_at=row[6],
        approved_at=row[7],
        dispatch_at=row[8],
        sent_at=row[9],
    )


class PostgresEmailStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresEmailStore:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def add_received(self, *, sender: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage(sender=sender, subject=subject, body=body)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO email_received ({_RECEIVED_COLUMNS}) VALUES (%s, %s, %s, %s, %s)",
                (message.id, message.sender, message.subject, message.body, message.received_at),
            )
        return message

    async def list_received(self) -> list[EmailMessage]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_RECEIVED_COLUMNS} FROM email_received ORDER BY received_at")
            rows = await cur.fetchall()
            return [_received_from_row(row) for row in rows]

    async def create_draft(
        self, *, to: str, subject: str, body: str, in_reply_to: str | None = None
    ) -> EmailDraft:
        draft = EmailDraft(to=to, subject=subject, body=body, in_reply_to=in_reply_to)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO email_drafts ({_DRAFT_COLUMNS_WITH_ID}) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    draft.id,
                    draft.to,
                    draft.subject,
                    draft.body,
                    draft.in_reply_to,
                    draft.status.value,
                    draft.created_at,
                    draft.approved_at,
                    draft.dispatch_at,
                    draft.sent_at,
                ),
            )
        return draft

    async def list_drafts(self, status: DraftStatus | None = None) -> list[EmailDraft]:
        async with self._pool.connection() as conn:
            if status is None:
                cur = await conn.execute(f"SELECT {_DRAFT_COLUMNS_WITH_ID} FROM email_drafts ORDER BY created_at")
            else:
                cur = await conn.execute(
                    f"SELECT {_DRAFT_COLUMNS_WITH_ID} FROM email_drafts WHERE status = %s ORDER BY created_at",
                    (status.value,),
                )
            rows = await cur.fetchall()
            return [_draft_from_row(row) for row in rows]

    async def get_draft(self, draft_id: str) -> EmailDraft | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_DRAFT_COLUMNS_WITH_ID} FROM email_drafts WHERE id = %s", (draft_id,))
            row = await cur.fetchone()
            return _draft_from_row(row) if row else None

    async def approve_draft(self, draft_id: str) -> EmailDraft | None:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, approved_at = %s "
                f"WHERE id = %s AND status = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.APPROVED.value, now, draft_id, DraftStatus.DRAFT.value),
            )
            row = await cur.fetchone()
            return _draft_from_row(row) if row else None

    async def queue_draft(self, draft_id: str, *, dispatch_at: datetime) -> EmailDraft | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, dispatch_at = %s "
                f"WHERE id = %s AND status = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.QUEUED.value, dispatch_at, draft_id, DraftStatus.APPROVED.value),
            )
            row = await cur.fetchone()
            return _draft_from_row(row) if row else None

    async def cancel_queued_draft(self, draft_id: str) -> EmailDraft | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, dispatch_at = NULL "
                f"WHERE id = %s AND status = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.APPROVED.value, draft_id, DraftStatus.QUEUED.value),
            )
            row = await cur.fetchone()
            return _draft_from_row(row) if row else None

    async def list_due(self, now: datetime) -> list[EmailDraft]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_DRAFT_COLUMNS_WITH_ID} FROM email_drafts "
                f"WHERE status = %s AND dispatch_at IS NOT NULL AND dispatch_at <= %s",
                (DraftStatus.QUEUED.value, now),
            )
            rows = await cur.fetchall()
            return [_draft_from_row(row) for row in rows]

    async def mark_sent(self, draft_id: str) -> EmailDraft | None:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, sent_at = %s "
                f"WHERE id = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.SENT.value, now, draft_id),
            )
            row = await cur.fetchone()
            return _draft_from_row(row) if row else None
