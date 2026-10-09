"""Schema-constrained (JSON) generation against the local vLLM for the atomic-claim arms: the same model, seed and temperature as the other arms, with `response_format` set to the claims schema. Non-streaming."""
from __future__ import annotations

import time

import httpx
from companion_core.knowledge.grounding.claims import SCHEMA

from aq import llm as llmlib


class LocalJSON(llmlib.Local):
    def complete_json(self, messages, *, max_tokens: int = 500) -> llmlib.Completion:
        body = {"model": llmlib.MODEL, "messages": messages, "temperature": 0, "seed": llmlib.SEED, "max_tokens": max_tokens,
                "response_format": {"type": "json_schema", "json_schema": {"name": "claims", "schema": SCHEMA}}}
        start = time.perf_counter()
        try:
            r = self.client.post("/v1/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return llmlib.Completion("", 0.0, (time.perf_counter() - start) * 1000, 0, 0, "error")
        end = time.perf_counter()
        usage = data.get("usage", {})
        choice = data["choices"][0]
        return llmlib.Completion(choice["message"]["content"] or "", (end - start) * 1000, (end - start) * 1000, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), choice.get("finish_reason"))
