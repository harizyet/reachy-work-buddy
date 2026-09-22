"""Direct proof of Phase 14's exit criterion ("No code path sends mail
without approval gate"): send_approved_draft is the only function that
ever calls a SendFn, and these tests assert the fake sender was never
invoked when the gate should have blocked it — not just that the right
exception was raised.
"""

import asyncio

from companion_core.email.models import DraftStatus, EmailDraft
from companion_core.email.store import InMemoryEmailStore
from companion_core.email.workflow import (
    DraftNotApprovedError,
    SendFn,
    send_approved_draft,
)


def _fake_send_fn() -> tuple[list[EmailDraft], SendFn]:
    sent: list[EmailDraft] = []

    async def send_fn(draft: EmailDraft) -> None:
        sent.append(draft)

    return sent, send_fn


def test_send_approved_draft_dispatches_and_marks_sent() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)

        result = await send_approved_draft(store, draft.id, send_fn=send_fn)

        assert result.status == DraftStatus.SENT
        assert len(sent) == 1
        assert sent[0].id == draft.id

    asyncio.run(run())


def test_send_unapproved_draft_raises_and_never_calls_send_fn() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")  # still DRAFT

        try:
            await send_approved_draft(store, draft.id, send_fn=send_fn)
            raise AssertionError("expected DraftNotApprovedError")
        except DraftNotApprovedError:
            pass

        assert sent == []  # the gate blocked dispatch before send_fn ever ran
        assert (await store.get_draft(draft.id)).status == DraftStatus.DRAFT

    asyncio.run(run())


def test_send_already_sent_draft_raises_and_never_calls_send_fn_again() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)
        await send_approved_draft(store, draft.id, send_fn=send_fn)
        assert len(sent) == 1

        try:
            await send_approved_draft(store, draft.id, send_fn=send_fn)
            raise AssertionError("expected DraftNotApprovedError")
        except DraftNotApprovedError:
            pass

        assert len(sent) == 1  # not sent a second time

    asyncio.run(run())


def test_send_unknown_draft_raises_lookup_error_and_never_calls_send_fn() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()

        try:
            await send_approved_draft(store, "nonexistent", send_fn=send_fn)
            raise AssertionError("expected LookupError")
        except LookupError:
            pass

        assert sent == []

    asyncio.run(run())
