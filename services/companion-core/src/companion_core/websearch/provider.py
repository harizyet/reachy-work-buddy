"""Provider-independent web-search abstraction (Phase 24a, docs/phase-24a.md).

One concrete adapter per provider normalizes to this shared SearchResult —
SearXNG's and each hosted provider's (Brave, Exa, Tavily) JSON responses are not shaped
alike, so a single generic HTTP adapter would have to guess at a schema
instead of each adapter owning its own. Everything above this layer
(policy, query building, prompt construction) is provider-independent and
operates only on SearchResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from shared.models.websearch import (
    HostedSearchProvider,
    SearchConfig,
    SearchFallbackKind,
)

# The bundled SearXNG container's address on the deployment's own compose
# network (deploy/homelab/docker-compose.yml's "searxng" service, port
# 8080, never published to the host) — Companion Core already knows this,
# so BUILTIN_SEARXNG needs no base_url from the operator (Phase 24
# cleanup). An external/custom SearXNG instance still supplies its own.
BUILTIN_SEARXNG_BASE_URL = "http://searxng:8080"


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source_domain: str


class SearchProvider(Protocol):
    async def search(self, query: str, *, count: int) -> list[SearchResult]: ...


class SearchProviderError(Exception):
    """Safe public error; never includes a URL, credential, or raw provider response."""


class SearchQuotaExhausted(SearchProviderError):
    """The provider reported its plan/credit limit reached (not a transient
    rate limit), so rotation stops sending it calls for the period."""


# 402 Payment Required, plus Tavily's plan (432) and pay-as-you-go (433)
# limits. A 429 is only a per-second rate limit and fails over normally.
QUOTA_STATUS_CODES = frozenset({402, 432, 433})


def raise_for_status(response) -> None:
    if response.status_code in QUOTA_STATUS_CODES:
        raise SearchQuotaExhausted("search provider reported its usage limit reached")
    response.raise_for_status()


def create_hosted_provider(
    kind: HostedSearchProvider, api_key: str, *, timeout_seconds: float, transport=None
) -> SearchProvider:
    if kind == HostedSearchProvider.BRAVE:
        from companion_core.websearch.brave import BraveSearchProvider as adapter
    elif kind == HostedSearchProvider.EXA:
        from companion_core.websearch.exa import ExaSearchProvider as adapter
    elif kind == HostedSearchProvider.TAVILY:
        from companion_core.websearch.tavily import TavilySearchProvider as adapter
    else:
        raise SearchProviderError("Unsupported search provider")
    return adapter(api_key, timeout_seconds=timeout_seconds, transport=transport)


def create_fallback_provider(config: SearchConfig, *, transport=None) -> SearchProvider | None:
    from companion_core.websearch.searxng import SearXNGSearchProvider

    if config.fallback == SearchFallbackKind.BUILTIN_SEARXNG:
        # No credential either: internal-only, never published to the
        # host — nothing outside the compose network can reach it.
        return SearXNGSearchProvider(
            BUILTIN_SEARXNG_BASE_URL,
            api_key=None,
            timeout_seconds=config.timeout_seconds,
            transport=transport,
        )
    if config.fallback == SearchFallbackKind.SEARXNG:
        if not config.base_url:
            raise SearchProviderError("No search provider base URL configured")
        return SearXNGSearchProvider(
            config.base_url,
            api_key=config.api_key,
            timeout_seconds=config.timeout_seconds,
            transport=transport,
        )
    return None
