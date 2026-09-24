"""Brave Search API adapter (Phase 24d). Queries go directly to Brave, so
the privacy note in the operator UI applies: a hosted provider receives
the query itself, unlike the bundled SearXNG's intermediary hop."""

from __future__ import annotations

import asyncio
import html
import re
from urllib.parse import urlsplit

import httpx

from companion_core.websearch.provider import SearchProviderError, SearchResult

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT_MARGIN_SECONDS = 1
_TAG = re.compile(r"<[^>]+>")


def _plain(text: object) -> str:
    return html.unescape(_TAG.sub("", str(text or "")))


class BraveSearchProvider:
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
                response = await client.get(
                    BRAVE_SEARCH_URL,
                    params={"q": query, "count": count, "text_decorations": "false"},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                )
                response.raise_for_status()
                data = response.json()
            items = (data.get("web") or {}).get("results") or []
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
            # Exception strings may contain the query, URL, or raw provider output.
            raise SearchProviderError(
                "search provider request failed or returned an invalid response"
            ) from None
        results = []
        for item in items[:count]:
            if not isinstance(item, dict) or not item.get("url") or not item.get("title"):
                continue
            url = str(item["url"])
            results.append(
                SearchResult(
                    title=_plain(item["title"]),
                    url=url,
                    snippet=_plain(item.get("description")),
                    source_domain=urlsplit(url).hostname or "",
                )
            )
        return results
