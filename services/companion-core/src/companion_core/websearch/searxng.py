"""SearXNG JSON API adapter (self-hosted by default). Reachy talks only to
this configured instance; SearXNG itself then forwards to whichever
upstream engines it's configured to use — see docs/phase-24a.md's Privacy
section for the exact wording this must not overstate."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx

from companion_core.websearch.provider import SearchProviderError, SearchResult

_TIMEOUT_MARGIN_SECONDS = 1


class SearXNGSearchProvider:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with (
                asyncio.timeout(self.timeout_seconds + _TIMEOUT_MARGIN_SECONDS),
                httpx.AsyncClient(
                    transport=self.transport,
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                ) as client,
            ):
                response = await client.get(
                    self.base_url + "/search",
                    params={"q": query, "format": "json"},
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError):
            # Exception strings may contain the query, URL, or raw provider output.
            raise SearchProviderError(
                "search provider request failed or returned an invalid response"
            ) from None
        results = []
        for item in (data.get("results") or [])[:count]:
            url = item.get("url")
            title = item.get("title")
            if not url or not title:
                continue
            results.append(
                SearchResult(
                    title=str(title),
                    url=str(url),
                    snippet=str(item.get("content") or ""),
                    source_domain=urlsplit(str(url)).hostname or "",
                )
            )
        return results
