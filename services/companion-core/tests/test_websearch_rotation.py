import asyncio
import json
import time
from datetime import UTC, datetime

import httpx
import pytest
from companion_core.websearch.exa import EXA_SEARCH_URL, ExaSearchProvider
from companion_core.websearch.provider import SearchProviderError
from companion_core.websearch.rotation import search_with_rotation
from companion_core.websearch.store import (
    InMemorySearchSettingsStore,
    merge_search_config,
)
from companion_core.websearch.tavily import TAVILY_SEARCH_URL, TavilySearchProvider

from shared.models.websearch import (
    HostedSearchProvider,
    SearchConfig,
    SearchConfigPatch,
)

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)
HOSTS = {
    "api.search.brave.com": "brave",
    "api.exa.ai": "exa",
    "api.tavily.com": "tavily",
    "searxng": "searxng",
}


def config(*, fallback="builtin_searxng", **limits):
    hosted = {
        kind: {"enabled": True, "api_key": f"{kind}-key", "monthly_limit": limit}
        for kind, limit in limits.items()
    }
    return merge_search_config(SearchConfig(), SearchConfigPatch.model_validate({
        "policy": "always", "fallback": fallback, "hosted": hosted,
    }))


def recording_transport(calls, *, status=None):
    """Answers every provider with one result in its own shape; `status`
    maps a provider name to an error status it returns instead."""
    def respond(request):
        name = HOSTS[request.url.host]
        calls.append(name)
        if status and name in status:
            return httpx.Response(status[name], text="error with key material")
        item = {"title": name, "url": f"https://{name}.example/"}
        if name == "brave":
            return httpx.Response(200, json={"web": {"results": [item]}})
        return httpx.Response(200, json={"results": [item]})
    return httpx.MockTransport(respond)


def run(cfg, store, transport, *, now=NOW):
    return asyncio.run(search_with_rotation(cfg, store, "query", now=now, transport=transport))


def test_load_spreads_across_hosted_providers_then_falls_back_at_the_caps():
    calls = []
    store = InMemorySearchSettingsStore()
    cfg = config(brave=2, exa=2, tavily=2)
    served = [run(cfg, store, recording_transport(calls))[0].title for _ in range(7)]

    assert served == ["brave", "exa", "tavily", "brave", "exa", "tavily", "searxng"]
    # No hosted provider is ever called past its cap.
    assert calls.count("brave") == calls.count("exa") == calls.count("tavily") == 2
    assert asyncio.run(store.usage("2026-09")) == {kind: 2 for kind in HostedSearchProvider}


def test_spread_is_proportional_to_each_monthly_limit():
    calls = []
    store = InMemorySearchSettingsStore()
    cfg = config(brave=1, exa=3)
    for _ in range(4):
        run(cfg, store, recording_transport(calls))
    assert sorted(calls) == ["brave", "exa", "exa", "exa"]


def test_counts_reset_with_the_calendar_month():
    calls = []
    store = InMemorySearchSettingsStore()
    cfg = config(brave=1, fallback="none")
    run(cfg, store, recording_transport(calls))
    with pytest.raises(SearchProviderError):
        run(cfg, store, recording_transport(calls))
    run(cfg, store, recording_transport(calls), now=datetime(2026, 10, 1, tzinfo=UTC))
    assert calls == ["brave", "brave"]


def test_failed_provider_fails_over_and_still_counts_the_attempt():
    calls = []
    store = InMemorySearchSettingsStore()
    results = run(config(brave=10, exa=10), store, recording_transport(calls, status={"brave": 500}))
    assert [r.title for r in results] == ["exa"]
    assert calls == ["brave", "exa"]
    usage = asyncio.run(store.usage("2026-09"))
    assert usage[HostedSearchProvider.BRAVE] == 1 and usage[HostedSearchProvider.EXA] == 1


@pytest.mark.parametrize("code", [402, 432, 433])
def test_provider_reported_quota_stops_calls_for_the_period(code):
    calls = []
    store = InMemorySearchSettingsStore()
    cfg = config(tavily=900, fallback="none")
    with pytest.raises(SearchProviderError):
        run(cfg, store, recording_transport(calls, status={"tavily": code}))
    with pytest.raises(SearchProviderError):
        run(cfg, store, recording_transport(calls))
    assert calls == ["tavily"]
    assert asyncio.run(store.usage("2026-09"))[HostedSearchProvider.TAVILY] == 900


def test_rate_limit_is_transient_and_does_not_exhaust():
    calls = []
    store = InMemorySearchSettingsStore()
    cfg = config(brave=900)
    assert run(cfg, store, recording_transport(calls, status={"brave": 429}))[0].title == "searxng"
    assert asyncio.run(store.usage("2026-09"))[HostedSearchProvider.BRAVE] == 1


def test_searxng_only_runs_when_no_hosted_provider_is_enabled():
    calls = []
    run(SearchConfig(policy="always"), InMemorySearchSettingsStore(), recording_transport(calls))
    assert calls == ["searxng"]


def test_disabled_provider_is_never_called_even_with_a_saved_key():
    calls = []
    cfg = merge_search_config(config(brave=5, exa=5), SearchConfigPatch.model_validate(
        {"hosted": {"brave": {"enabled": False}}},
    ))
    assert cfg.hosted[HostedSearchProvider.BRAVE].api_key == "brave-key"
    for _ in range(3):
        run(cfg, InMemorySearchSettingsStore(), recording_transport(calls))
    assert calls == ["exa", "exa", "exa"]


def test_whole_chain_is_bounded_by_twice_the_timeout():
    async def hang(request):
        await asyncio.sleep(10)

    cfg = merge_search_config(config(brave=5, exa=5, tavily=5), SearchConfigPatch(timeout_seconds=0.05))
    started = time.monotonic()
    with pytest.raises(SearchProviderError):
        run(cfg, InMemorySearchSettingsStore(), httpx.MockTransport(hang))
    # Each tier alone may run 1.05 s (timeout plus adapter margin); the chain stops at 0.1 s.
    assert time.monotonic() - started < 1


def test_exa_adapter_sends_key_and_uses_highlights_as_snippet():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"results": [
            {"title": "Istana", "url": "https://www.istana.gov.sg/", "highlights": ["President Tharman", "since 2023"]},
            {"title": "no url"},
        ], "costDollars": {"total": 0.008}})

    results = asyncio.run(ExaSearchProvider("exa-secret", transport=httpx.MockTransport(respond)).search("q", count=3))
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == EXA_SEARCH_URL and seen[0].headers["x-api-key"] == "exa-secret"
    assert body["numResults"] == 3 and body["contents"] == {"highlights": True}
    assert [(r.title, r.snippet, r.source_domain) for r in results] == [
        ("Istana", "President Tharman … since 2023", "www.istana.gov.sg"),
    ]


def test_tavily_adapter_uses_one_credit_basic_search():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"results": [
            {"title": "Istana", "url": "https://www.istana.gov.sg/", "content": "President Tharman"},
        ]})

    results = asyncio.run(TavilySearchProvider("tvly-secret", transport=httpx.MockTransport(respond)).search("q", count=4))
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == TAVILY_SEARCH_URL and seen[0].headers["Authorization"] == "Bearer tvly-secret"
    assert body == {"query": "q", "max_results": 4, "search_depth": "basic"}
    assert results[0].snippet == "President Tharman"


@pytest.mark.parametrize("adapter", [ExaSearchProvider, TavilySearchProvider])
@pytest.mark.parametrize("response", [
    httpx.Response(401, text="invalid key hosted-secret"),
    httpx.Response(200, content=b"not json"),
    httpx.Response(200, json={"results": "unexpected"}),
])
def test_hosted_adapter_failures_are_safe_errors(adapter, response):
    provider = adapter("hosted-secret", transport=httpx.MockTransport(lambda r: response))
    try:
        results = asyncio.run(provider.search("anything", count=3))
    except SearchProviderError as exc:
        assert "hosted-secret" not in str(exc)
    else:
        assert results == []
