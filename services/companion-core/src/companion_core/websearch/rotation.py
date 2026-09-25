"""Spread each turn's single search across the hosted providers so every
one stays inside its free tier (Phase 24d).

Per turn: the enabled hosted providers are tried in order of the fraction
of their monthly cap already used (least first, declaration order on ties),
so load spreads in proportion to each allowance rather than draining one
before touching the next. A call is counted before it is sent — a failed
request may still be billed — and a provider at its cap is skipped, never
called. A provider error moves on to the next tier; SearXNG runs only after
every hosted tier failed, was capped, or none is enabled, because its
scraped upstream engines are the least dependable from a home address.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from companion_core.websearch.debug_log import SearchAttempt
from companion_core.websearch.provider import (
    SearchProviderError,
    SearchQuotaExhausted,
    SearchResult,
    create_fallback_provider,
    create_hosted_provider,
)
from companion_core.websearch.store import SearchSettingsStore, usage_period
from shared.models.websearch import HostedSearchProvider, SearchConfig

logger = logging.getLogger(__name__)

# Bounds the whole chain, not each tier, so a hanging provider plus
# failovers can't hold a voice turn for tiers × timeout. Each tier still
# has its own timeout_seconds.
CHAIN_TIMEOUT_FACTOR = 2


async def rotation_order(
    config: SearchConfig, store: SearchSettingsStore, period: str
) -> list[HostedSearchProvider]:
    usage = await store.usage(period)
    enabled = [
        kind for kind in HostedSearchProvider
        if config.hosted[kind].enabled and config.hosted[kind].api_key
    ]
    rank = list(HostedSearchProvider)
    return sorted(enabled, key=lambda kind: (usage[kind] / config.hosted[kind].monthly_limit, rank.index(kind)))


async def search_with_rotation(
    config: SearchConfig,
    store: SearchSettingsStore,
    query: str,
    *,
    now: datetime,
    transport=None,
    attempts: list[SearchAttempt] | None = None,
) -> list[SearchResult]:
    """`attempts`, when given, receives one entry per tier tried or skipped,
    for the owner's debug log."""
    period = usage_period(now)
    attempts = [] if attempts is None else attempts
    started = time.monotonic()
    current = None

    def note(provider: str, outcome: str) -> None:
        nonlocal started, current
        current = None
        attempts.append(SearchAttempt(provider, outcome, round((time.monotonic() - started) * 1000)))
        started = time.monotonic()

    try:
        async with asyncio.timeout(config.timeout_seconds * CHAIN_TIMEOUT_FACTOR):
            for kind in await rotation_order(config, store, period):
                hosted = config.hosted[kind]
                if not await store.reserve(kind, period, hosted.monthly_limit):
                    note(kind.value, "at_limit")
                    continue
                current = kind.value
                provider = create_hosted_provider(
                    kind, hosted.api_key, timeout_seconds=config.timeout_seconds, transport=transport,
                )
                try:
                    results = await provider.search(query, count=config.result_count)
                except SearchQuotaExhausted:
                    logger.warning("web search provider %s reported its usage limit; skipping it until next period", kind.value)
                    await store.exhaust(kind, period, hosted.monthly_limit)
                    note(kind.value, "limit_reported")
                    continue
                except SearchProviderError:
                    logger.warning("web search provider %s failed; trying next tier", kind.value)
                    note(kind.value, "error")
                    continue
                logger.info("web search served by %s", kind.value)
                note(kind.value, "ok")
                return results
            fallback = create_fallback_provider(config, transport=transport)
            if fallback is None:
                raise SearchProviderError("No search provider available")
            current = config.fallback.value
            try:
                results = await fallback.search(query, count=config.result_count)
            except SearchProviderError:
                note(current, "error")
                raise
            logger.info("web search served by fallback %s", config.fallback.value)
            note(current, "ok")
            return results
    except TimeoutError:
        if current is not None:
            note(current, "timeout")
        raise SearchProviderError("search providers timed out") from None
