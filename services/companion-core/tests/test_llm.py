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
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
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
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
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
            assert [m["role"] for m in seen[1]] == ["system", "user", "assistant", "user"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode,force,failure,roles,reason",
    [
        ("local_only", False, False, ["local"], None),
        ("local_only", False, True, ["local"], None),
        ("local_with_cloud_fallback", False, False, ["local"], None),
        ("local_with_cloud_fallback", False, True, ["local", "cloud"], "error"),
        ("cloud_only", False, False, ["cloud"], None),
        ("local_only", True, False, ["cloud"], "manual"),
        ("local_with_cloud_fallback", True, False, ["cloud"], "manual"),
        ("cloud_only", True, False, ["cloud"], "manual"),
    ],
)
def test_role_routing_and_attempt_accounting(mode, force, failure, roles, reason):
    seen = []

    def respond(request):
        role = request.url.host
        seen.append(role)
        if role == "local" and failure:
            raise httpx.ConnectError("secret URL", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": role}}]})

    client = TestClient(core_app(llm_transport=httpx.MockTransport(respond)))
    assert (
        client.put(
            "/settings/llm",
            json={
                "local": {"base_url": "http://local/v1", "model": "same-model"},
                "cloud": {"base_url": "http://cloud/v1", "model": "same-model"},
                "routing": {"mode": mode},
            },
        ).status_code
        == 200
    )
    reply = client.post(
        "/conversation",
        json={
            "session_id": "s",
            "conversation_id": "c",
            "channel": "web",
            "text": "Hello there",
            "force_frontier": force,
        },
    ).json()["reply"]
    assert seen == roles
    assert (
        reply == roles[-1]
        if not (failure and roles == ["local"])
        else "unavailable" in reply
    )
    usage = client.get("/llm/usage").json()
    assert usage["summary"]["calls"] == len(roles)
    assert usage["by_role"]["cloud"]["calls"] == roles.count("cloud")
    assert usage["by_role"]["local"]["errors"] == int(failure and "local" in roles)
    assert [e["role"] for e in reversed(usage["entries"])] == roles
    assert usage["entries"][0]["escalation_reason"] == reason
    assert (
        usage["latest_escalation"]["reason"] if reason else usage["latest_escalation"]
    ) == reason
    assert "secret URL" not in str(usage)


def test_cloud_partial_settings_preserve_keys_and_explicit_policy():
    client = TestClient(core_app())
    local = {"base_url": "http://local/v1", "model": "local", "api_key": "local-secret"}
    cloud = {
        "base_url": "https://cloud/v1",
        "model": "cloud",
        "api_key": "cloud-secret",
    }
    client.put("/settings/llm", json={"local": local})
    result = client.put("/settings/llm", json={"cloud": cloud}).json()
    assert result["routing"]["mode"] == "local_with_cloud_fallback"
    assert result["local"]["model"] == "local"
    result = client.put(
        "/settings/llm", json={"routing": {"mode": "local_only"}}
    ).json()
    result = client.put("/settings/llm", json={"cloud": {"model": "new"}}).json()
    assert result["routing"]["mode"] == "local_only"
    assert result["cloud"]["api_key"] == "********cret"
    assert result["local"]["api_key"] == "********cret"
    assert (
        client.put("/settings/llm", json={"cloud": {"api_key": None}}).json()["cloud"][
            "api_key"
        ]
        is None
    )
    assert client.put("/settings/llm", json={"cloud": None}).status_code == 200
    assert (
        client.put(
            "/settings/llm", json={"cloud": cloud, "routing": {"mode": "local_only"}}
        ).json()["routing"]["mode"]
        == "local_only"
    )


def test_missing_frontier_never_falls_back_to_local_and_intents_still_win():
    def unexpected(request):
        pytest.fail(
            "An explicit cloud request or deterministic intent must not call local"
        )

    client = TestClient(core_app(llm_transport=httpx.MockTransport(unexpected)))
    turn = {
        "session_id": "s",
        "conversation_id": "c",
        "channel": "web",
        "text": "Hello",
        "force_frontier": True,
    }
    assert "unavailable" in client.post("/conversation", json=turn).json()["reply"]
    client.put(
        "/settings/llm", json={"local": {"base_url": "http://local", "model": "local"}}
    )
    assert "unavailable" in client.post("/conversation", json=turn).json()["reply"]
    turn["text"] = "remind me to review the report"
    assert "unavailable" not in client.post("/conversation", json=turn).json()["reply"]
    assert client.get("/llm/usage").json()["summary"]["calls"] == 0


def test_cloud_failure_and_cancellation_do_not_retry():
    async def run():
        from companion_core.llm.router import route_completion

        from shared.models.llm import LLMConfig

        config = LLMConfig(
            local={"base_url": "http://local", "model": "l"},
            cloud={"base_url": "http://cloud", "model": "c"},
            routing={"mode": "local_with_cloud_fallback"},
        )
        store = InMemoryLLMUsageStore()
        with pytest.raises(ProviderUnavailable):
            await route_completion(
                config,
                [],
                store,
                transport=httpx.MockTransport(lambda r: httpx.Response(503)),
            )
        assert len(await store.list_recent(10)) == 2
        calls = []

        def cancel(request):
            calls.append(request.url.host)
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await route_completion(
                config, [], store, transport=httpx.MockTransport(cancel)
            )
        assert calls == ["local"]
        assert (await store.list_recent(1))[0].error_message == "cancelled"

    asyncio.run(run())


def test_total_provider_deadline_triggers_fallback(monkeypatch):
    import companion_core.llm.client as client_module
    from companion_core.llm.router import route_completion

    from shared.models.llm import LLMConfig

    monkeypatch.setattr(client_module, "PROVIDER_TIMEOUT_SECONDS", 0.02)

    async def run():
        async def respond(request):
            if request.url.host == "local":
                await asyncio.sleep(1)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "cloud"}}]}
            )

        config = LLMConfig(
            local={"base_url": "http://local", "model": "l"},
            cloud={"base_url": "http://cloud", "model": "c"},
            routing={"mode": "local_with_cloud_fallback"},
        )
        store = InMemoryLLMUsageStore()
        assert (
            await route_completion(
                config, [], store, transport=httpx.MockTransport(respond)
            )
            == "cloud"
        )
        entries = await store.list_recent(2)
        assert entries[1].error_message != "cancelled"
        assert entries[0].escalation_reason == "error"

    asyncio.run(run())
