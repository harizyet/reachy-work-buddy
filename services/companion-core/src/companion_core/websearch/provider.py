"""Provider-independent web-search abstraction (Phase 24a, docs/phase-24a.md).

One concrete adapter per provider normalizes to this shared SearchResult —
SearXNG's and a hosted provider's (e.g. Brave) JSON responses are not shaped
alike, so a single generic HTTP adapter would have to guess at a schema
instead of each adapter owning its own. Everything above this layer
(policy, query building, prompt construction) is provider-independent and
operates only on SearchResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from shared.models.websearch import SearchConfig, SearchProviderKind

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


def create_provider(config: SearchConfig, *, transport=None) -> SearchProvider:
    if config.provider == SearchProviderKind.BUILTIN_SEARXNG:
        from companion_core.websearch.searxng import SearXNGSearchProvider

        # No credential either: internal-only, never published to the
        # host — nothing outside the compose network can reach it.
        return SearXNGSearchProvider(
            BUILTIN_SEARXNG_BASE_URL,
            api_key=None,
            timeout_seconds=config.timeout_seconds,
            transport=transport,
        )
    if config.provider == SearchProviderKind.SEARXNG:
        from companion_core.websearch.searxng import SearXNGSearchProvider

        if not config.base_url:
            raise SearchProviderError("No search provider base URL configured")
        return SearXNGSearchProvider(
            config.base_url,
            api_key=config.api_key,
            timeout_seconds=config.timeout_seconds,
            transport=transport,
        )
    raise SearchProviderError("Unsupported search provider")
