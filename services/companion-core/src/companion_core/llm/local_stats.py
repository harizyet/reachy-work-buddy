"""Live stats of the local vLLM server for the owner's Overview card.

Reads vLLM's own `/health`, `/v1/models` and Prometheus `/metrics` at the configured local provider's base URL, with
the same credentials and no redirects as a completion. Only a fixed set of numbers is passed on, never the raw
exposition text, so a misconfigured local URL cannot turn this route into a page proxy.
"""

from __future__ import annotations

import asyncio
import math
import re

import httpx

from shared.models.llm import ProviderConfig

STATS_TIMEOUT_SECONDS = 3.0

_SAMPLE = re.compile(r'^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>\S+)')


def parse_samples(text: str) -> dict[str, float]:
    """Sum every series of a metric across its label sets (engines, finish reasons), ignoring comments and non-numbers."""
    totals: dict[str, float] = {}
    for line in text.splitlines():
        match = _SAMPLE.match(line)
        if not match:
            continue
        try:
            value = float(match["value"])
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        totals[match["name"]] = totals.get(match["name"], 0.0) + value
    return totals


def _first(samples: dict[str, float], *names: str) -> float | None:
    return next((samples[n] for n in names if n in samples), None)


def _mean(samples: dict[str, float], base: str) -> float | None:
    total, count = samples.get(f"{base}_sum"), samples.get(f"{base}_count")
    return total / count if total is not None and count else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return numerator / denominator if numerator is not None and denominator else None


def summarize_metrics(text: str) -> dict:
    s = parse_samples(text)
    # vLLM renamed the cache gauge between its v0 and v1 engines.
    cache = _first(s, "vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc")
    return {
        "requests_running": _first(s, "vllm:num_requests_running"),
        "requests_waiting": _first(s, "vllm:num_requests_waiting"),
        "kv_cache_usage": cache,
        "prompt_tokens_total": _first(s, "vllm:prompt_tokens_total"),
        "generation_tokens_total": _first(s, "vllm:generation_tokens_total"),
        "requests_finished_total": _first(s, "vllm:request_success_total"),
        "preemptions_total": _first(s, "vllm:num_preemptions_total"),
        "mean_time_to_first_token_s": _mean(s, "vllm:time_to_first_token_seconds"),
        "mean_e2e_latency_s": _mean(s, "vllm:e2e_request_latency_seconds"),
        "prefix_cache_hit_rate": _ratio(_first(s, "vllm:prefix_cache_hits_total"), _first(s, "vllm:prefix_cache_queries_total")),
    }


async def fetch_local_stats(config: ProviderConfig | None, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """`{"status": "not_configured" | "unavailable" | "ok", ...}`; never raises for a provider problem."""
    if config is None:
        return {"status": "not_configured"}
    root = config.base_url.removesuffix("/v1")
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    try:
        async with asyncio.timeout(STATS_TIMEOUT_SECONDS * 2), httpx.AsyncClient(
            transport=transport, timeout=STATS_TIMEOUT_SECONDS, follow_redirects=False, headers=headers
        ) as client:
            health, models, metrics = await asyncio.gather(
                client.get(f"{root}/health"), client.get(f"{root}/v1/models"), client.get(f"{root}/metrics"),
                return_exceptions=True,
            )
            if isinstance(health, BaseException) or health.status_code != 200:
                return {"status": "unavailable"}
            model: dict = {}
            if not isinstance(models, BaseException) and models.status_code == 200:
                try:
                    first = models.json()["data"][0]
                    model = {"id": str(first["id"]), "max_model_len": first.get("max_model_len")}
                except (ValueError, KeyError, IndexError, TypeError):
                    model = {}
            result = {"status": "ok", "model": model or None, "metrics": None}
            if not isinstance(metrics, BaseException) and metrics.status_code == 200:
                result["metrics"] = summarize_metrics(metrics.text)
            return result
    except (httpx.HTTPError, TimeoutError):
        return {"status": "unavailable"}
