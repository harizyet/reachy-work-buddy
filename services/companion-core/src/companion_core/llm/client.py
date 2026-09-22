import asyncio
from time import perf_counter
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from companion_core.llm.store import LLMUsageStore
from shared.models.llm import LLMUsageEntry, ProviderConfig


class ChatProvider(Protocol):
    async def complete(self, history: list[dict[str, str]]) -> str: ...


class ProviderUnavailable(Exception):
    """Safe public error; never includes a URL, credential, or provider response."""


class _Message(BaseModel):
    content: str = Field(min_length=1)


class _Choice(BaseModel):
    message: _Message


class _Usage(BaseModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


class _Completion(BaseModel):
    choices: list[_Choice] = Field(min_length=1)
    usage: _Usage | None = None


class OpenAICompatibleChatProvider:
    def __init__(self, config: ProviderConfig, usage: LLMUsageStore, *, transport=None):
        self.config = config
        self.usage = usage
        self.transport = transport

    async def complete(self, history: list[dict[str, str]]) -> str:
        entry = LLMUsageEntry(model=self.config.model)
        start = perf_counter()
        try:
            headers = (
                {"Authorization": f"Bearer {self.config.api_key}"}
                if self.config.api_key
                else {}
            )
            # Redirects must never carry credentials to a different endpoint.
            async with httpx.AsyncClient(
                transport=self.transport, timeout=60, follow_redirects=False
            ) as client:
                response = await client.post(
                    self.config.base_url + "/chat/completions",
                    headers=headers,
                    json={
                        "model": self.config.model,
                        "messages": history,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                completion = _Completion.model_validate(response.json())
                content = completion.choices[0].message.content
                if not content.strip():
                    raise ValueError("Empty completion")
                if completion.usage:
                    entry.prompt_tokens = completion.usage.prompt_tokens
                    entry.completion_tokens = completion.usage.completion_tokens
                entry.success = True
                return content
        except asyncio.CancelledError:
            entry.error_message = "cancelled"
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            # Exception strings may contain keys, URLs, or private provider output.
            entry.error_message = (
                "provider request failed or returned an invalid completion"
            )
            raise ProviderUnavailable(entry.error_message) from None
        finally:
            entry.latency_ms = (perf_counter() - start) * 1000
            await self.usage.append(entry)
