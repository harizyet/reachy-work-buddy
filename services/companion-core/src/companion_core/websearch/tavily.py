"""Tavily Search API adapter (Phase 24a follow-up). Like Brave, a hosted provider
receives the query itself."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx

from companion_core.websearch.provider import (
    SearchProviderError,
    SearchResult,
    raise_for_status,
)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TIMEOUT_MARGIN_SECONDS = 1


class TavilySearchProvider:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        try:
            async with (
                asyncio.timeout(self.timeout_seconds + _TIMEOUT_MARGIN_SECONDS),
                httpx.AsyncClient(
                    transport=self.transport,
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                ) as client,
            ):
                # "basic" costs one credit; "advanced" costs two, which would
                # halve the free allowance the monthly cap is sized for.
                response = await client.post(
                    TAVILY_SEARCH_URL,
                    json={"query": query, "max_results": count, "search_depth": "basic"},
                    headers={"Accept": "application/json", "Authorization": f"Bearer {self.api_key}"},
                )
                raise_for_status(response)
                items = response.json().get("results") or []
        except (asyncio.CancelledError, SearchProviderError):
            raise
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
            # Exception strings may contain the query, URL, or raw provider output.
            raise SearchProviderError(
                "search provider request failed or returned an invalid response"
            ) from None
        results = []
        for item in items[:count] if isinstance(items, list) else []:
            if not isinstance(item, dict) or not item.get("url") or not item.get("title"):
                continue
            url = str(item["url"])
            results.append(
                SearchResult(
                    title=str(item["title"]),
                    url=url,
                    snippet=str(item.get("content") or ""),
                    source_domain=urlsplit(url).hostname or "",
                )
            )
        return results
