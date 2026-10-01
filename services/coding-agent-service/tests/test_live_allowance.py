"""29.26: live account allowance from the provider's usage endpoint, with the
fetch and token refresh injected so no test touches the network or a real
token."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from coding_agent_service.claude_provider import (
    ACCOUNT_CREDENTIAL,
    ClaudeCodeProvider,
    _live_allowance_dimensions,
)
from coding_agent_service.credentials import InMemoryCredentialStore
from coding_agent_service.providers import ProviderError
from coding_agent_service.runtime import SimulatedContainerRuntime
from coding_agent_service.service import CodingAgentSupervisor
from coding_agent_service.store import InMemoryCodingAgentStore

from shared.models.coding_agent import CredentialKind

FUTURE = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
BODY = {
    "five_hour": {"utilization": 42.5, "resets_at": FUTURE},
    "seven_day": {"utilization": 10, "resets_at": FUTURE},
    "seven_day_opus": None,
    "extra": {"utilization": 99},
}


def _ms(delta: timedelta) -> int:
    return int((datetime.now(UTC) + delta).timestamp() * 1000)


def _blob(
    *,
    expires: timedelta = timedelta(hours=4),
    access: str = "acc-1",
    refresh: str = "ref-1",
) -> str:
    # The shape of ~/.claude/.credentials.json.
    return json.dumps(
        {
            "claudeAiOauth": {
                "accessToken": access,
                "refreshToken": refresh,
                "expiresAt": _ms(expires),
            }
        }
    )


async def _provider(blob: str | None, fetch, refresh=None):
    store = InMemoryCodingAgentStore()
    credentials = InMemoryCredentialStore()
    if blob is not None:
        await credentials.set_credential(
            ACCOUNT_CREDENTIAL, CredentialKind.OAUTH_TOKEN, blob
        )
    provider = ClaudeCodeProvider(
        SimulatedContainerRuntime(),
        credentials,
        store,
        usage_fetch=fetch,
        token_refresh=refresh
        or (lambda tok: (_ for _ in ()).throw(AssertionError("unexpected refresh"))),
    )
    return provider, store, credentials


def test_parses_known_windows_and_skips_null_or_malformed() -> None:
    dims = _live_allowance_dimensions(
        {**BODY, "seven_day_sonnet": {"utilization": "x", "resets_at": FUTURE}}
    )
    assert [(d.name, d.value, d.unit) for d in dims] == [
        ("five_hour_window", 42.5, "%"),
        ("weekly_window", 10.0, "%"),
    ]


def test_live_allowance_needs_the_account_credential() -> None:
    async def run() -> None:
        seen = []
        provider, _, _ = await _provider(_blob(), lambda tok: seen.append(tok) or BODY)
        assert len(await provider.live_allowance()) == 2
        assert seen == ["acc-1"]
        # A session credential alone never reaches the usage endpoint.
        none, _, session_only = await _provider(
            None, lambda tok: seen.append("leak") or BODY
        )
        await session_only.set_credential(
            "claude-code", CredentialKind.OAUTH_TOKEN, "setup-token-fixture"
        )
        assert await none.live_allowance() is None
        assert "leak" not in seen

    asyncio.run(run())


def test_expiring_token_is_refreshed_and_the_rotated_pair_persisted() -> None:
    async def run() -> None:
        used = []
        refreshed = []

        def refresh(tok):
            refreshed.append(tok)
            return {
                "access_token": "acc-2",
                "refresh_token": "ref-2",
                "expires_in": 28800,
            }

        provider, _, credentials = await _provider(
            _blob(expires=timedelta(minutes=1)),
            lambda tok: used.append(tok) or BODY,
            refresh,
        )
        await provider.live_allowance()
        assert refreshed == ["ref-1"] and used == ["acc-2"]
        saved = json.loads(await credentials.get_secret(ACCOUNT_CREDENTIAL))[
            "claudeAiOauth"
        ]
        assert (saved["accessToken"], saved["refreshToken"]) == ("acc-2", "ref-2")
        assert saved["expiresAt"] > _ms(timedelta(hours=7))
        await provider.live_allowance()
        assert refreshed == ["ref-1"]

    asyncio.run(run())


def test_a_401_triggers_one_refresh_and_retry() -> None:
    async def run() -> None:
        calls = []

        def fetch(tok):
            calls.append(tok)
            if tok == "acc-1":
                raise ProviderError(
                    "Claude usage endpoint refused the request (HTTP 401)"
                )
            return BODY

        provider, _, _ = await _provider(
            _blob(),
            fetch,
            lambda tok: {
                "access_token": "acc-2",
                "refresh_token": "ref-2",
                "expires_in": 3600,
            },
        )
        assert len(await provider.live_allowance()) == 2
        assert calls == ["acc-1", "acc-2"]

    asyncio.run(run())


def test_supervisor_prefers_live_and_falls_back_on_provider_error() -> None:
    async def run() -> None:
        provider, store, _ = await _provider(_blob(), lambda tok: BODY)
        supervisor = CodingAgentSupervisor(store, {"claude-code": provider})
        live = await supervisor.provider_allowance("claude-code")
        assert live.source == "live" and len(live.windows) == 2

        def refuse(tok):
            raise ProviderError("refused (HTTP 403)")

        provider._usage_fetch = refuse
        fallback = await supervisor.provider_allowance("claude-code")
        assert fallback.source == "last_reported" and fallback.windows == []

    asyncio.run(run())
