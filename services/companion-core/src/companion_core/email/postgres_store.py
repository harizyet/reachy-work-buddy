"""Postgres-backed EmailStore. See store.py for the interface and the
approval-gate/delayed-queue note in models.py/workflow.py."""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

from companion_core.email.models import (
    AttachmentMeta,
    DraftStatus,
    EmailDraft,
    EmailEvent,
    EmailMessage,
    Recipients,
    package_hash,
)
from companion_core.email.store import EDITABLE, Blob, _meta
from shared.database import check_schema, close_pool, open_pool

_RECEIVED_COLUMNS = "id, sender, subject, body, received_at"
_DRAFT_COLUMNS = (
    '"to", subject, body, in_reply_to, status, created_at, approved_at, dispatch_at, sent_at, kind, recipients, source, package_hash, approved_hash, message_id, sender, '
    "attempts, claimed_at, last_error, provider_response"
)
_DRAFT_COLUMNS_WITH_ID = f"id, {_DRAFT_COLUMNS}"


def _received_from_row(row: tuple) -> EmailMessage:
    return EmailMessage(id=row[0], sender=row[1], subject=row[2], body=row[3], received_at=row[4])


def _draft_from_row(row: tuple) -> EmailDraft:
    return EmailDraft(
        id=row[0], to=row[1], subject=row[2], body=row[3], in_reply_to=row[4], status=DraftStatus(row[5]), created_at=row[6], approved_at=row[7], dispatch_at=row[8],
        sent_at=row[9], kind=row[10], recipients=Recipients(**row[11]) if row[11] else None, source=row[12], package_hash=row[13], approved_hash=row[14], message_id=row[15],
        sender=row[16], attempts=row[17], claimed_at=row[18], last_error=row[19], provider_response=row[20],
    )


class PostgresEmailStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresEmailStore:
        pool = await open_pool(dsn)
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await close_pool(self._pool)

    async def _hydrate(self, conn, rows: list[tuple]) -> list[EmailDraft]:
        drafts = [_draft_from_row(row) for row in rows]
        if drafts:
            cur = await conn.execute(
                "SELECT draft_id, name, content_type, sha256, size FROM email_draft_attachments WHERE draft_id = ANY(%s) ORDER BY name", ([d.id for d in drafts],))
            by_draft: dict[str, list[AttachmentMeta]] = {}
            for draft_id, name, ctype, sha, size in await cur.fetchall():
                by_draft.setdefault(draft_id, []).append(AttachmentMeta(name=name, content_type=ctype, sha256=sha, size=size))
            for draft in drafts:
                draft.attachments = by_draft.get(draft.id, [])
        return drafts

    async def _one(self, conn, cur) -> EmailDraft | None:
        row = await cur.fetchone()
        return (await self._hydrate(conn, [row]))[0] if row else None

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
                "INSERT INTO email_drafts (id, \"to\", subject, body, in_reply_to, status, created_at, approved_at, dispatch_at, sent_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (draft.id, draft.to, draft.subject, draft.body, draft.in_reply_to, draft.status.value, draft.created_at, draft.approved_at, draft.dispatch_at, draft.sent_at),
            )
        return draft

    async def create_package(self, draft: EmailDraft, blobs: list[Blob]) -> EmailDraft:
        import hashlib

        draft = draft.model_copy(update={"attachments": _meta(blobs), "attachment_blobs": []})
        draft.package_hash = package_hash(draft, draft.sender)
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO email_drafts (id, \"to\", subject, body, in_reply_to, status, created_at, kind, recipients, source, package_hash, sender) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (draft.id, draft.to, draft.subject, draft.body, draft.in_reply_to, draft.status.value, draft.created_at, draft.kind,
                 Json(draft.recipients.model_dump()) if draft.recipients else None, Json(draft.source) if draft.source is not None else None, draft.package_hash, draft.sender))
            for name, ctype, data in blobs:
                await conn.execute("INSERT INTO email_draft_attachments (draft_id, name, content_type, sha256, size, data) VALUES (%s,%s,%s,%s,%s,%s)",
                                   (draft.id, name, ctype, hashlib.sha256(data).hexdigest(), len(data), data))
        return draft

    async def list_drafts(self, status: DraftStatus | None = None, *, kind: str | None = None) -> list[EmailDraft]:
        clauses, args = [], []
        if status is not None:
            clauses.append("status = %s"); args.append(status.value)
        if kind is not None:
            clauses.append("kind = %s"); args.append(kind)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_DRAFT_COLUMNS_WITH_ID} FROM email_drafts{where} ORDER BY created_at", args)
            return await self._hydrate(conn, await cur.fetchall())

    async def get_draft(self, draft_id: str) -> EmailDraft | None:
        async with self._pool.connection() as conn:
            return await self._one(conn, await conn.execute(f"SELECT {_DRAFT_COLUMNS_WITH_ID} FROM email_drafts WHERE id = %s", (draft_id,)))

    async def get_blobs(self, draft_id: str) -> list[Blob]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT name, content_type, data FROM email_draft_attachments WHERE draft_id = %s ORDER BY name", (draft_id,))
            return [(n, c, bytes(d)) for n, c, d in await cur.fetchall()]

    async def update_package(self, draft_id, *, recipients, subject, body, sender, blobs=None, source=None):
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute(f"SELECT {_DRAFT_COLUMNS_WITH_ID} FROM email_drafts WHERE id = %s FOR UPDATE", (draft_id,))
            current = await self._one(conn, cur)
            if current is None or current.status not in EDITABLE:
                return None
            if blobs is not None:
                import hashlib

                await conn.execute("DELETE FROM email_draft_attachments WHERE draft_id = %s", (draft_id,))
                for name, ctype, data in blobs:
                    await conn.execute("INSERT INTO email_draft_attachments (draft_id, name, content_type, sha256, size, data) VALUES (%s,%s,%s,%s,%s,%s)",
                                       (draft_id, name, ctype, hashlib.sha256(data).hexdigest(), len(data), data))
                current.attachments = _meta(blobs)
            current.recipients, current.subject, current.body, current.sender = recipients, subject, body, sender
            if source is not None:
                current.source = source
            current.to = recipients.to[0] if recipients.to else current.to
            new_hash = package_hash(current, sender)
            # Any change returns the package to review: an earlier approval covered different content.
            cur = await conn.execute(
                f"UPDATE email_drafts SET recipients = %s, subject = %s, body = %s, sender = %s, \"to\" = %s, source = %s, package_hash = %s, status = %s, approved_hash = NULL, approved_at = NULL, dispatch_at = NULL "
                f"WHERE id = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (Json(recipients.model_dump()), subject, body, sender, current.to, Json(current.source) if current.source is not None else None, new_hash, DraftStatus.READY_FOR_REVIEW.value, draft_id))
            return await self._one(conn, cur)

    async def approve_draft(self, draft_id: str) -> EmailDraft | None:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, approved_at = %s WHERE id = %s AND status = %s AND kind = 'text' RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.APPROVED.value, now, draft_id, DraftStatus.DRAFT.value))
            return await self._one(conn, cur)

    async def approve_reviewed(self, draft_id: str, *, package_hash: str, message_id: str) -> EmailDraft | None:
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, approved_at = %s, approved_hash = %s, message_id = %s WHERE id = %s AND status = %s AND package_hash = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.APPROVED.value, now, package_hash, message_id, draft_id, DraftStatus.READY_FOR_REVIEW.value, package_hash))
            return await self._one(conn, cur)

    async def queue_draft(self, draft_id: str, *, dispatch_at: datetime) -> EmailDraft | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, dispatch_at = %s WHERE id = %s AND status = %s AND approved_hash IS NOT DISTINCT FROM package_hash RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.QUEUED.value, dispatch_at, draft_id, DraftStatus.APPROVED.value))
            return await self._one(conn, cur)

    async def cancel_queued_draft(self, draft_id: str) -> EmailDraft | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, dispatch_at = NULL WHERE id = %s AND status = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.APPROVED.value, draft_id, DraftStatus.QUEUED.value))
            return await self._one(conn, cur)

    async def discard_draft(self, draft_id: str) -> EmailDraft | None:
        allowed = [s.value for s in (*EDITABLE, DraftStatus.QUEUED, DraftStatus.FAILED, DraftStatus.UNKNOWN_DELIVERY)]
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, dispatch_at = NULL WHERE id = %s AND status = ANY(%s) RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.CANCELLED.value, draft_id, allowed))
            return await self._one(conn, cur)

    async def list_due(self, now: datetime) -> list[EmailDraft]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_DRAFT_COLUMNS_WITH_ID} FROM email_drafts WHERE status = %s AND dispatch_at IS NOT NULL AND dispatch_at <= %s",
                (DraftStatus.QUEUED.value, now))
            return await self._hydrate(conn, await cur.fetchall())

    async def claim_due(self, now: datetime) -> EmailDraft | None:
        """One due draft, atomically: QUEUED to SENDING in a single statement that skips rows another worker has locked, so two workers can never send the same draft."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, claimed_at = %s, attempts = attempts + 1 WHERE id = ("
                f"SELECT id FROM email_drafts WHERE status = %s AND dispatch_at IS NOT NULL AND dispatch_at <= %s AND approved_hash IS NOT DISTINCT FROM package_hash "
                f"ORDER BY dispatch_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.SENDING.value, now, DraftStatus.QUEUED.value, now))
            return await self._one(conn, cur)

    async def _settle(self, draft_id: str, status: DraftStatus, sets: str, args: tuple) -> EmailDraft | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, claimed_at = NULL, {sets} WHERE id = %s AND status = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (status.value, *args, draft_id, DraftStatus.SENDING.value))
            return await self._one(conn, cur)

    async def mark_sent(self, draft_id: str, *, provider_response: str | None = None) -> EmailDraft | None:
        settled = await self._settle(draft_id, DraftStatus.SENT, "sent_at = %s, provider_response = %s, last_error = NULL", (datetime.now(UTC), provider_response))
        if settled is not None:
            return settled
        async with self._pool.connection() as conn:  # a plain queued draft (older call sites) or the owner's own reconciliation of an unknown delivery
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, sent_at = %s, provider_response = %s WHERE id = %s AND status = ANY(%s) RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.SENT.value, datetime.now(UTC), provider_response, draft_id, [DraftStatus.QUEUED.value, DraftStatus.UNKNOWN_DELIVERY.value]))
            return await self._one(conn, cur)

    async def mark_failed(self, draft_id: str, *, error: str) -> EmailDraft | None:
        return await self._settle(draft_id, DraftStatus.FAILED, "last_error = %s", (error[:300],))

    async def mark_unknown(self, draft_id: str, *, error: str) -> EmailDraft | None:
        return await self._settle(draft_id, DraftStatus.UNKNOWN_DELIVERY, "last_error = %s", (error[:300],))

    async def requeue_for_retry(self, draft_id: str, *, dispatch_at: datetime, error: str) -> EmailDraft | None:
        return await self._settle(draft_id, DraftStatus.QUEUED, "dispatch_at = %s, last_error = %s", (dispatch_at, error[:300]))

    async def recover_stuck(self, older_than: datetime | None) -> list[EmailDraft]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE email_drafts SET status = %s, claimed_at = NULL, last_error = %s WHERE status = %s AND (%s::timestamptz IS NULL OR (claimed_at IS NOT NULL AND claimed_at < %s::timestamptz)) RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                (DraftStatus.UNKNOWN_DELIVERY.value, "the process stopped while this message was being sent; it may or may not have been delivered", DraftStatus.SENDING.value, older_than, older_than))
            return await self._hydrate(conn, await cur.fetchall())

    async def resolve_unknown(self, draft_id: str, *, delivered: bool) -> EmailDraft | None:
        async with self._pool.connection() as conn:
            if delivered:
                cur = await conn.execute(
                    f"UPDATE email_drafts SET status = %s, sent_at = %s WHERE id = %s AND status = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                    (DraftStatus.SENT.value, datetime.now(UTC), draft_id, DraftStatus.UNKNOWN_DELIVERY.value))
            else:  # a fresh review and approval, and a new Message-ID
                cur = await conn.execute(
                    f"UPDATE email_drafts SET status = %s, approved_hash = NULL, approved_at = NULL, dispatch_at = NULL, message_id = NULL, attempts = 0 WHERE id = %s AND status = %s RETURNING {_DRAFT_COLUMNS_WITH_ID}",
                    (DraftStatus.READY_FOR_REVIEW.value, draft_id, DraftStatus.UNKNOWN_DELIVERY.value))
            return await self._one(conn, cur)

    async def add_event(self, draft_id: str, event: str, detail: dict | None = None) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("INSERT INTO email_draft_events (draft_id, at, event, detail) VALUES (%s,%s,%s,%s)", (draft_id, datetime.now(UTC), event, Json(detail or {})))

    async def list_events(self, draft_id: str) -> list[EmailEvent]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT at, event, detail FROM email_draft_events WHERE draft_id = %s ORDER BY id", (draft_id,))
            return [EmailEvent(draft_id=draft_id, at=at, event=event, detail=detail) for at, event, detail in await cur.fetchall()]
