"""Direct proof of docs/adr/0011's delayed-send requirement: "send draft
X" only queues a dispatch ~10 minutes out, dispatch_due_drafts is the only
function that ever calls a SendFn, and it only dispatches what's actually
due — controlled `now` values stand in for real elapsed time so these
tests don't need real sleeps.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from companion_core.email.models import DraftStatus, EmailDraft
from companion_core.email.store import InMemoryEmailStore
from companion_core.email.workflow import (
    DraftNotApprovedError,
    DraftNotQueuedError,
    SendFn,
    cancel_queued_draft,
    dispatch_due_drafts,
    queue_draft_for_sending,
    run_dispatch_loop,
)


def _fake_send_fn() -> tuple[list[EmailDraft], SendFn]:
    sent: list[EmailDraft] = []

    async def send_fn(draft: EmailDraft) -> None:
        sent.append(draft)

    return sent, send_fn


def test_queue_draft_for_sending_requires_approval_first() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")  # still DRAFT

        try:
            await queue_draft_for_sending(store, draft.id)
            raise AssertionError("expected DraftNotApprovedError")
        except DraftNotApprovedError:
            pass

    asyncio.run(run())


def test_queue_draft_for_sending_sets_status_and_dispatch_at() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)

        queued = await queue_draft_for_sending(store, draft.id, delay_seconds=600)
        assert queued.status == DraftStatus.QUEUED
        assert queued.dispatch_at is not None
        assert queued.dispatch_at > datetime.now(UTC) + timedelta(minutes=9)

    asyncio.run(run())


def test_dispatch_due_drafts_never_dispatches_before_its_time() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)
        await queue_draft_for_sending(store, draft.id, delay_seconds=600)

        # "Now" is still well before the 10-minute dispatch_at.
        dispatched = await dispatch_due_drafts(store, send_fn=send_fn, now=datetime.now(UTC))
        assert dispatched == 0
        assert sent == []
        assert (await store.get_draft(draft.id)).status == DraftStatus.QUEUED

    asyncio.run(run())


def test_dispatch_due_drafts_sends_once_the_window_has_passed() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)
        await queue_draft_for_sending(store, draft.id, delay_seconds=600)

        later = datetime.now(UTC) + timedelta(minutes=11)
        dispatched = await dispatch_due_drafts(store, send_fn=send_fn, now=later)

        assert dispatched == 1
        assert len(sent) == 1
        assert sent[0].id == draft.id
        assert (await store.get_draft(draft.id)).status == DraftStatus.SENT

    asyncio.run(run())


def test_cancel_queued_draft_reverts_to_approved_and_prevents_dispatch() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)
        await queue_draft_for_sending(store, draft.id, delay_seconds=600)

        cancelled = await cancel_queued_draft(store, draft.id)
        assert cancelled.status == DraftStatus.APPROVED
        assert cancelled.dispatch_at is None

        # Even "well past" the original dispatch_at, nothing is sent —
        # cancelling actually prevents dispatch, not just changes a label.
        later = datetime.now(UTC) + timedelta(minutes=30)
        dispatched = await dispatch_due_drafts(store, send_fn=send_fn, now=later)
        assert dispatched == 0
        assert sent == []

    asyncio.run(run())


def test_cancel_queued_draft_on_a_non_queued_draft_raises() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")  # DRAFT, never queued

        try:
            await cancel_queued_draft(store, draft.id)
            raise AssertionError("expected DraftNotQueuedError")
        except DraftNotQueuedError:
            pass

    asyncio.run(run())


def test_dispatch_due_drafts_only_touches_whats_actually_due() -> None:
    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()

        soon = await store.create_draft(to="soon@example.com", subject="Soon", body="body")
        await store.approve_draft(soon.id)
        await queue_draft_for_sending(store, soon.id, delay_seconds=1)

        later_draft = await store.create_draft(to="later@example.com", subject="Later", body="body")
        await store.approve_draft(later_draft.id)
        await queue_draft_for_sending(store, later_draft.id, delay_seconds=3600)

        now_plus_a_bit = datetime.now(UTC) + timedelta(seconds=5)
        dispatched = await dispatch_due_drafts(store, send_fn=send_fn, now=now_plus_a_bit)

        assert dispatched == 1
        assert sent[0].to == "soon@example.com"
        assert (await store.get_draft(later_draft.id)).status == DraftStatus.QUEUED

    asyncio.run(run())


def test_run_dispatch_loop_is_a_real_background_task() -> None:
    """One real-task sanity check with a short interval, same split
    AGENTS.md documents for the presence/heartbeat loops: the step
    function above gets the deterministic-time coverage, this just proves
    the loop itself actually runs and calls it repeatedly."""

    async def run() -> None:
        store = InMemoryEmailStore()
        sent, send_fn = _fake_send_fn()
        draft = await store.create_draft(to="a@example.com", subject="Hi", body="Hello")
        await store.approve_draft(draft.id)
        await queue_draft_for_sending(store, draft.id, delay_seconds=0)  # already due

        task = asyncio.create_task(run_dispatch_loop(store, send_fn=send_fn, interval_seconds=0.05))
        try:
            for _ in range(100):  # up to ~0.5s
                if sent:
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert len(sent) == 1
        assert (await store.get_draft(draft.id)).status == DraftStatus.SENT

    asyncio.run(run())
