"""29.26: live account allowance from the provider's usage endpoint, with
the fetch injected so no test touches the network or a real token."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from coding_agent_service.claude_provider import (
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


async def _provider(kind: CredentialKind | None, fetch):
    store = InMemoryCodingAgentStore()
    credentials = InMemoryCredentialStore()
    if kind is not None:
        await credentials.set_credential("claude-code", kind, "tok-fixture-1234")
    return ClaudeCodeProvider(SimulatedContainerRuntime(), credentials, store, usage_fetch=fetch), store


def test_parses_known_windows_and_skips_null_or_malformed() -> None:
    dims = _live_allowance_dimensions({**BODY, "seven_day_sonnet": {"utilization": "x", "resets_at": FUTURE}})
    assert [(d.name, d.value, d.unit) for d in dims] == [("five_hour_window", 42.5, "%"), ("weekly_window", 10.0, "%")]


def test_live_allowance_uses_oauth_token_only() -> None:
    async def run() -> None:
        seen = []
        provider, _ = await _provider(CredentialKind.OAUTH_TOKEN, lambda tok: seen.append(tok) or BODY)
        assert len(await provider.live_allowance()) == 2
        assert seen == ["tok-fixture-1234"]
        api, _ = await _provider(CredentialKind.API_KEY, lambda tok: seen.append("leak") or BODY)
        assert await api.live_allowance() is None
        none, _ = await _provider(None, lambda tok: BODY)
        assert await none.live_allowance() is None
        assert "leak" not in seen

    asyncio.run(run())


def test_supervisor_prefers_live_and_falls_back_on_provider_error() -> None:
    async def run() -> None:
        provider, store = await _provider(CredentialKind.OAUTH_TOKEN, lambda tok: BODY)
        supervisor = CodingAgentSupervisor(store, {"claude-code": provider})
        live = await supervisor.provider_allowance("claude-code")
        assert live.source == "live" and len(live.windows) == 2

        def refuse(tok):
            raise ProviderError("refused (HTTP 403)")

        provider._usage_fetch = refuse
        fallback = await supervisor.provider_allowance("claude-code")
        assert fallback.source == "last_reported" and fallback.windows == []

    asyncio.run(run())
