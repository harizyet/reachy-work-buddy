import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.client import OpenAICompatibleChatProvider, ProviderUnavailable
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from fastapi.testclient import TestClient

from shared.models.llm import LLMConfigPatch, LLMUsageEntry, ProviderConfig


def core_app(**kwargs):
    return create_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        run_email_dispatch_task=False,
        **kwargs,
    )


def test_provider_records_real_request_and_usage():
    async def run():
        store = InMemoryLLMUsageStore()

        def respond(request):
            assert str(request.url) == "http://ovms/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer private-key"
            assert json.loads(request.content) == {
                "model": "configured-model",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Hello there"}}],
                    "usage": {"prompt_tokens": 6, "completion_tokens": 2},
                },
            )

        provider = OpenAICompatibleChatProvider(
            ProviderConfig(
                base_url="http://ovms/v1/",
                model="configured-model",
                api_key="private-key",
            ),
            store,
            transport=httpx.MockTransport(respond),
        )
        assert (
            await provider.complete([{"role": "user", "content": "hello"}])
            == "Hello there"
        )
        (entry,) = await store.list_recent(10)
        assert (
            entry.success and entry.prompt_tokens == 6 and entry.completion_tokens == 2
        )
        assert entry.latency_ms > 0 and entry.role == "local"

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["http", "timeout", "invalid", "empty", "redirect"])
def test_failure_logged_without_secrets(failure):
    async def run():
        store = InMemoryLLMUsageStore()

        def respond(request):
            if failure == "timeout":
                raise httpx.ReadTimeout("private-key", request=request)
            if failure == "http":
                return httpx.Response(500, text="private-key")
            if failure == "redirect":
                return httpx.Response(302, headers={"Location": "http://another-host"})
            return httpx.Response(
                200,
                json={}
                if failure == "invalid"
                else {"choices": [{"message": {"content": ""}}]},
            )

        provider = OpenAICompatibleChatProvider(
            ProviderConfig(
                base_url="http://ovms/v1", model="qwen", api_key="private-key"
            ),
            store,
            transport=httpx.MockTransport(respond),
        )
        with pytest.raises(ProviderUnavailable):
            await provider.complete([])
        (entry,) = await store.list_recent(10)
        assert not entry.success
        assert "private-key" not in entry.model_dump_json()

    asyncio.run(run())


def test_local_provider_needs_no_key_and_usage_may_be_unreported():
    async def run():
        store = InMemoryLLMUsageStore()

        def respond(request):
            assert "authorization" not in request.headers
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "answer"}}]}
            )

        provider = OpenAICompatibleChatProvider(
            ProviderConfig(base_url="http://ovms/v1", model="qwen"),
            store,
            transport=httpx.MockTransport(respond),
        )
        await provider.complete([])
        summary = await store.summary(datetime.now(UTC) - timedelta(hours=1))
        assert summary["summary"]["unreported_token_calls"] == 1
        assert summary["by_role"]["cloud"]["calls"] == 0

    asyncio.run(run())


def test_settings_merge_mask_validation_and_disable():
    client = TestClient(core_app())
    assert client.get("/settings/llm").json()["local"] is None
    settings = {
        "local": {
            "base_url": "http://ovms/v1",
            "model": "qwen",
            "api_key": "super-private-key",
        }
    }
    result = client.put("/settings/llm", json=settings)
    assert result.status_code == 200 and "super-private-key" not in result.text
    assert result.json()["local"]["api_key"].endswith("-key")
    assert (
        client.put("/settings/llm", json={"local": {"model": "new"}})
        .json()["local"]["api_key"]
        .endswith("-key")
    )
    assert client.put("/settings/llm", json={}).json()["local"]["model"] == "new"
    assert (
        client.put(
            "/settings/llm", json={"local": {"base_url": "file:///tmp/file"}}
        ).status_code
        == 422
    )
    assert client.get("/settings/llm").json()["local"]["base_url"] == "http://ovms/v1"
    assert (
        client.put(
            "/settings/llm", json={"routing": {"mode": "cloud_only"}}
        ).status_code
        == 422
    )
    assert (
        client.put("/settings/llm", json={"local": {"api_key": None}}).json()["local"][
            "api_key"
        ]
        is None
    )
    assert client.put("/settings/llm", json={"local": None}).json()["local"] is None
    assert (
        client.put(
            "/settings/llm", json={"local": {"model": "missing-url"}}
        ).status_code
        == 422
    )
    assert client.get("/llm/usage?limit=0").status_code == 422
    assert client.get("/llm/usage?since_hours=-1").status_code == 422


def test_conversation_uses_history_but_intents_do_not_call_provider():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Model reply"}}]}
        )

    client = TestClient(core_app(llm_transport=httpx.MockTransport(respond)))
    turn = {
        "session_id": "session",
        "conversation_id": "conversation",
        "channel": "web",
        "text": "Hello",
    }
    assert "heard:" in client.post("/conversation", json=turn).json()["reply"]
    client.put(
        "/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}}
    )
    assert client.post("/conversation", json=turn).json()["reply"] == "Model reply"
    turn["text"] = "Tell me more"
    assert client.post("/conversation", json=turn).json()["turn_count"] == 3
    assert requests[-1]["messages"][-2] == {
        "role": "assistant",
        "content": "Model reply",
    }
    turn["text"] = "remind me to review the report"
    client.post("/conversation", json=turn)
    assert len(requests) == 2
    usage = client.get("/llm/usage?limit=1").json()
    assert len(usage["entries"]) == 1 and usage["summary"]["calls"] == 2


def test_unavailable_provider_is_an_honest_reply():
    client = TestClient(
        core_app(llm_transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    )
    client.put(
        "/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}}
    )
    response = client.post(
        "/conversation",
        json={
            "session_id": "session",
            "conversation_id": "conversation",
            "channel": "web",
            "text": "Hello",
        },
    )
    assert response.status_code == 200 and "unavailable" in response.json()["reply"]
    assert client.get("/llm/usage").json()["summary"]["errors"] == 1


def test_usage_window_is_independent_of_recent_limit():
    async def run():
        store = InMemoryLLMUsageStore()
        await store.append(
            LLMUsageEntry(model="old", at=datetime.now(UTC) - timedelta(days=2))
        )
        await store.append(
            LLMUsageEntry(
                model="new", success=True, prompt_tokens=10, completion_tokens=5
            )
        )
        summary = await store.summary(datetime.now(UTC) - timedelta(hours=1))
        assert summary["summary"]["calls"] == 1 and summary["summary"]["errors"] == 0
        assert summary["summary"]["prompt_tokens"] == 10
        settings = InMemoryLLMSettingsStore()
        await settings.set(
            LLMConfigPatch(
                local={"base_url": "http://local", "model": "model", "api_key": "abcd"}
            )
        )
        from companion_core.llm.store import masked_config

        assert masked_config(await settings.get())["local"]["api_key"] == "********"

    asyncio.run(run())


def test_settings_validation_does_not_echo_credentials():
    client = TestClient(core_app())
    for body in (
        {"local": {"api_key": {"secret": "do-not-echo"}}},
        {"local": {"base_url": "http://name:do-not-echo@host", "model": "qwen"}},
    ):
        response = client.put("/settings/llm", json=body)
        assert response.status_code == 422 and "do-not-echo" not in response.text


def test_generated_followups_preserve_private_context():
    client = TestClient(
        core_app(
            llm_transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": "Here are more details."}}]
                    },
                )
            )
        )
    )
    client.put(
        "/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}}
    )
    turn = {
        "session_id": "private",
        "conversation_id": "private",
        "channel": "web",
        "text": "What is my next meeting?",
    }
    assert client.post("/conversation", json=turn).json()["privacy"] == "work-private"
    turn["text"] = "Tell me more"
    assert client.post("/conversation", json=turn).json()["privacy"] == "work-private"
    turn.update(session_id="other", conversation_id="other")
    assert client.post("/conversation", json=turn).json()["privacy"] == "public"


def test_simultaneous_channels_keep_user_assistant_order():
    async def run():
        seen = []

        async def respond(request):
            seen.append(json.loads(request.content)["messages"])
            await asyncio.sleep(0)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "Reply"}}]}
            )

        app = core_app(llm_transport=httpx.MockTransport(respond))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://core"
        ) as client:
            await client.put(
                "/settings/llm",
                json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}},
            )

            async def send(channel):
                return await client.post(
                    "/conversation",
                    json={
                        "session_id": "same",
                        "conversation_id": "same",
                        "channel": channel,
                        "text": "Hello",
                    },
                )

            results = await asyncio.gather(send("web"), send("telegram"))
            assert all(r.status_code == 200 for r in results)
            assert [m["role"] for m in seen[1]] == ["user", "assistant", "user"]

    asyncio.run(run())
