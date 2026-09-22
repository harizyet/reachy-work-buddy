"""Direct proof of docs/adr/0011's two hard rules. Same asyncio.run
wrapper pattern as the other *_store tests (no pytest-asyncio/anyio plugin
installed)."""

import asyncio

from companion_core.consent.gate import (
    BulkActionBlockedError,
    ConfirmationExpiredError,
    ConfirmationNotFoundError,
    VoiceConfirmationNotAllowedError,
    confirm_action,
    request_confirmation,
)
from companion_core.consent.models import ActionScope, ConfirmationStatus
from companion_core.consent.store import InMemoryConfirmationStore

from shared.models.session import InputModality


def test_bulk_scope_is_always_blocked_no_row_ever_created() -> None:
    """The hard block the user asked for: "if an llm decides the best
    outcome is to delete the whole mailbox, this should always be
    blocked" — there is no confirmation to approve because none is ever
    created."""

    async def run() -> None:
        store = InMemoryConfirmationStore()
        try:
            await request_confirmation(
                store, action_type="email.delete_all", target_id="*", description="entire mailbox", scope=ActionScope.BULK
            )
            raise AssertionError("expected BulkActionBlockedError")
        except BulkActionBlockedError:
            pass

        # Nothing was created — not even a rejected/expired row to confirm later.
        assert await store.find_pending("email.delete_all", "mailbox") is None

    asyncio.run(run())


def test_single_scope_creates_a_pending_confirmation() -> None:
    async def run() -> None:
        store = InMemoryConfirmationStore()
        request = await request_confirmation(
            store, action_type="memory.forget", target_id="m1", description="my manager is Alice"
        )
        assert request.status == ConfirmationStatus.PENDING
        assert request.scope == ActionScope.SINGLE

    asyncio.run(run())


def test_voice_can_never_confirm_a_destructive_action() -> None:
    async def run() -> None:
        store = InMemoryConfirmationStore()
        request = await request_confirmation(
            store, action_type="memory.forget", target_id="m1", description="my manager is Alice"
        )

        try:
            await confirm_action(store, request.id, input_modality=InputModality.VOICE)
            raise AssertionError("expected VoiceConfirmationNotAllowedError")
        except VoiceConfirmationNotAllowedError:
            pass

        # Still pending — the voice attempt didn't consume or alter it.
        reloaded = await store.get(request.id)
        assert reloaded.status == ConfirmationStatus.PENDING

    asyncio.run(run())


def test_text_confirms_successfully() -> None:
    async def run() -> None:
        store = InMemoryConfirmationStore()
        request = await request_confirmation(
            store, action_type="memory.forget", target_id="m1", description="my manager is Alice"
        )

        confirmed = await confirm_action(store, request.id, input_modality=InputModality.TEXT)
        assert confirmed.status == ConfirmationStatus.CONFIRMED
        assert confirmed.confirmed_at is not None

    asyncio.run(run())


def test_confirming_unknown_id_raises_not_found() -> None:
    async def run() -> None:
        store = InMemoryConfirmationStore()
        try:
            await confirm_action(store, "nonexistent", input_modality=InputModality.TEXT)
            raise AssertionError("expected ConfirmationNotFoundError")
        except ConfirmationNotFoundError:
            pass

    asyncio.run(run())


def test_expired_confirmation_cannot_be_confirmed() -> None:
    async def run() -> None:
        store = InMemoryConfirmationStore()
        request = await request_confirmation(
            store, action_type="memory.forget", target_id="m1", description="my manager is Alice", ttl_seconds=-1
        )

        try:
            await confirm_action(store, request.id, input_modality=InputModality.TEXT)
            raise AssertionError("expected ConfirmationExpiredError")
        except ConfirmationExpiredError:
            pass

    asyncio.run(run())


def test_confirming_twice_fails_the_second_time() -> None:
    async def run() -> None:
        store = InMemoryConfirmationStore()
        request = await request_confirmation(
            store, action_type="memory.forget", target_id="m1", description="my manager is Alice"
        )
        await confirm_action(store, request.id, input_modality=InputModality.TEXT)

        try:
            await confirm_action(store, request.id, input_modality=InputModality.TEXT)
            raise AssertionError("expected ConfirmationExpiredError")
        except ConfirmationExpiredError:
            pass

    asyncio.run(run())


def test_find_pending_matches_description_substring() -> None:
    async def run() -> None:
        store = InMemoryConfirmationStore()
        await request_confirmation(
            store, action_type="memory.forget", target_id="m1", description="my manager is Alice"
        )

        found = await store.find_pending("memory.forget", "alice")  # case-insensitive
        assert found is not None
        assert found.target_id == "m1"

        assert await store.find_pending("memory.forget", "nobody") is None

    asyncio.run(run())
