import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from reachy_hub.telegram_client import TelegramClient
from reachy_hub.telegram_health import TelegramPollHealth, poll_updates

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)


def test_disabled_starting_and_stale_health():
    health = TelegramPollHealth()
    assert health.snapshot(configured=False, now=NOW) == {
        "configured": False,
        "healthy": False,
        "last_poll_at": None,
        "last_poll_error": None,
    }
    assert not health.snapshot(configured=True, now=NOW)["healthy"]
    health.last_poll_at = NOW
    assert health.snapshot(configured=True, now=NOW + timedelta(seconds=59))["healthy"]
    assert not health.snapshot(configured=True, now=NOW + timedelta(seconds=60))[
        "healthy"
    ]
    assert not health.snapshot(configured=False, now=NOW)["healthy"]
    assert not health.snapshot(configured=True, now=NOW - timedelta(seconds=1))[
        "healthy"
    ]


def test_idle_success_updates_health_and_preserves_poll_options():
    async def run():
        health = TelegramPollHealth()

        def respond(request):
            assert request.url.params["timeout"] == "25"
            assert request.url.params["offset"] == "42"
            return httpx.Response(200, json={"ok": True, "result": []})

        client = TelegramClient("private-token", transport=httpx.MockTransport(respond))
        try:
            assert await poll_updates(client, health, offset=42, now=NOW) == []
            assert health.snapshot(configured=True, now=NOW)["healthy"]
            assert health.last_poll_at == NOW
        finally:
            await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", ["http", "timeout", "invalid_json", "api_error", "invalid_updates"]
)
def test_failures_mark_unhealthy_without_exposing_token_and_recover(failure):
    async def run():
        health = TelegramPollHealth(last_poll_at=NOW)
        failing = True

        def respond(request):
            if not failing:
                return httpx.Response(
                    200, json={"ok": True, "result": [{"update_id": 7}]}
                )
            if failure == "http":
                return httpx.Response(401, text="secret-token")
            if failure == "timeout":
                raise httpx.ReadTimeout("secret-token", request=request)
            if failure == "invalid_json":
                return httpx.Response(200, text="secret-token")
            if failure == "api_error":
                return httpx.Response(
                    200, json={"ok": False, "description": "secret-token"}
                )
            return httpx.Response(200, json={"ok": True, "result": ["secret-token"]})

        client = TelegramClient("secret-token", transport=httpx.MockTransport(respond))
        try:
            with pytest.raises((httpx.HTTPError, ValueError)):
                await poll_updates(client, health, now=NOW + timedelta(seconds=1))
            assert health.last_poll_at == NOW
            failed = health.snapshot(configured=True, now=NOW + timedelta(seconds=1))
            assert not failed["healthy"] and failed["last_poll_error"]
            assert "secret-token" not in str(failed)
            failing = False
            assert await poll_updates(
                client, health, now=NOW + timedelta(seconds=3)
            ) == [{"update_id": 7}]
            assert health.last_poll_at == NOW + timedelta(seconds=3)
            assert health.last_poll_error is None
            assert health.snapshot(configured=True, now=health.last_poll_at)["healthy"]
        finally:
            await client.aclose()

    asyncio.run(run())
