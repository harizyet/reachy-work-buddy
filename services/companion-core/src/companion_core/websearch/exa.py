"""Exa Search API adapter (Phase 24d). Like Brave, a hosted provider
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

EXA_SEARCH_URL = "https://api.exa.ai/search"
_TIMEOUT_MARGIN_SECONDS = 1


class ExaSearchProvider:
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
                # Highlights are billed as contents on top of the search; full
                # text would cost more and overflow the local model's context.
                response = await client.post(
                    EXA_SEARCH_URL,
                    json={"query": query, "numResults": count, "type": "fast", "contents": {"highlights": True}},
                    headers={"Accept": "application/json", "x-api-key": self.api_key},
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
            highlights = item.get("highlights")
            snippet = " … ".join(map(str, highlights)) if isinstance(highlights, list) else ""
            results.append(
                SearchResult(
                    title=str(item["title"]),
                    url=url,
                    snippet=snippet or str(item.get("summary") or item.get("text") or ""),
                    source_domain=urlsplit(url).hostname or "",
                )
            )
        return results
