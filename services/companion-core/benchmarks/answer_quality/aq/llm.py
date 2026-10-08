"""A streaming client for the local vLLM (the production T1 model, served as `reachy-local`): time to first token, total time and exact usage,
at temperature 0 with a fixed seed. Token counts for the budget come from the server's own tokenizer."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import httpx

BASE = os.environ.get("AQ_LLM_URL", "http://localhost:8003")
MODEL = os.environ.get("AQ_LLM_MODEL", "reachy-local")
SEED = 44


@dataclass
class Completion:
    text: str
    ttft_ms: float
    total_ms: float
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None


class Local:
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=BASE, timeout=120)
        self._counts: dict[str, int] = {}

    def healthy(self) -> bool:
        try:
            return self.client.get("/health", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False

    def count_tokens(self, text: str) -> int:
        if text not in self._counts:
            r = self.client.post("/tokenize", json={"model": MODEL, "prompt": text, "add_special_tokens": False})
            r.raise_for_status()
            self._counts[text] = int(r.json()["count"])
        return self._counts[text]

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 350) -> Completion:
        body = {"model": MODEL, "messages": messages, "stream": True, "stream_options": {"include_usage": True},
                "temperature": 0, "seed": SEED, "max_tokens": max_tokens}
        start = time.perf_counter()
        first: float | None = None
        parts: list[str] = []
        usage: dict = {}
        finish = None
        with self.client.stream("POST", "/v1/chat/completions", json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                data = json.loads(payload)
                if data.get("usage"):
                    usage = data["usage"]
                for choice in data.get("choices", []):
                    piece = choice.get("delta", {}).get("content")
                    if piece:
                        if first is None:
                            first = time.perf_counter()
                        parts.append(piece)
                    finish = choice.get("finish_reason") or finish
        end = time.perf_counter()
        return Completion("".join(parts), ((first or end) - start) * 1000, (end - start) * 1000,
                          int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), finish)
