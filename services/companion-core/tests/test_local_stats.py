import asyncio

import httpx
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.local_stats import (
    fetch_local_stats,
    parse_samples,
    summarize_metrics,
)
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.llm import ProviderConfig


def core_app(**kwargs):
    return create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False, **kwargs,
    )

METRICS = """# HELP vllm:num_requests_running Running
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="reachy-local"} 2.0
vllm:num_requests_waiting{engine="0",model_name="reachy-local"} 1.0
vllm:kv_cache_usage_perc{engine="0",model_name="reachy-local"} 0.25
vllm:prompt_tokens_total{engine="0",model_name="reachy-local"} 1000.0
vllm:generation_tokens_total{engine="0",model_name="reachy-local"} 400.0
vllm:request_success_total{engine="0",finished_reason="stop"} 7.0
vllm:request_success_total{engine="0",finished_reason="length"} 1.0
vllm:time_to_first_token_seconds_sum{engine="0"} 4.0
vllm:time_to_first_token_seconds_count{engine="0"} 8.0
vllm:prefix_cache_hits_total{engine="0"} 30.0
vllm:prefix_cache_queries_total{engine="0"} 120.0
vllm:bad{x="y"} notanumber
"""


def vllm(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer k"
    path = request.url.path
    if path == "/health":
        return httpx.Response(200)
    if path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "reachy-local", "max_model_len": 8192}]})
    return httpx.Response(200, text=METRICS)


CONFIG = ProviderConfig(base_url="http://vllm:8000/v1", model="reachy-local", api_key="k")


def test_parse_sums_series_and_skips_junk():
    samples = parse_samples(METRICS)
    assert samples["vllm:request_success_total"] == 8.0
    assert "vllm:bad" not in samples
    summary = summarize_metrics(METRICS)
    assert summary["requests_running"] == 2.0 and summary["kv_cache_usage"] == 0.25
    assert summary["mean_time_to_first_token_s"] == 0.5 and summary["prefix_cache_hit_rate"] == 0.25
    assert summary["mean_e2e_latency_s"] is None


def test_fetch_ok_unavailable_and_not_configured():
    asyncio.run(_fetch_cases())


async def _fetch_cases():
    ok = await fetch_local_stats(CONFIG, transport=httpx.MockTransport(vllm))
    assert ok["status"] == "ok" and ok["model"] == {"id": "reachy-local", "max_model_len": 8192}
    assert ok["metrics"]["generation_tokens_total"] == 400.0
    assert (await fetch_local_stats(None))["status"] == "not_configured"
    down = httpx.MockTransport(lambda r: httpx.Response(503))
    assert (await fetch_local_stats(CONFIG, transport=down))["status"] == "unavailable"

    def refuse(request):
        raise httpx.ConnectError("no route")

    assert (await fetch_local_stats(CONFIG, transport=httpx.MockTransport(refuse)))["status"] == "unavailable"


def test_metrics_missing_still_reports_healthy():
    asyncio.run(_no_metrics_case())


async def _no_metrics_case():
    def no_metrics(request):
        return httpx.Response(404) if request.url.path == "/metrics" else vllm(request)

    result = await fetch_local_stats(CONFIG, transport=httpx.MockTransport(no_metrics))
    assert result["status"] == "ok" and result["metrics"] is None


def test_route_uses_configured_local_provider_and_never_leaks_key():
    with TestClient(core_app(llm_transport=httpx.MockTransport(vllm))) as client:
        assert client.get("/llm/local-stats").json() == {"status": "not_configured"}
        client.put("/settings/llm", json={"local": {"base_url": "http://vllm:8000/v1", "model": "reachy-local", "api_key": "k"}})
        body = client.get("/llm/local-stats")
        assert body.json()["status"] == "ok" and "api_key" not in body.text and "Bearer" not in body.text
