"""The PostgreSQL retrieval configurations as benchmark adapters (Phase 44D): B1a lexical, B1b lexical + vector fused by reciprocal rank,
B1c with a cross-encoder reranker. Each retrieves through the index and is then revalidated against the stores under the case's
AccessContext; what the harness scores is what would reach a model. The candidates before revalidation are reported too, so the
report can separate what the search proposed from what was exposed."""

from __future__ import annotations

import os
import resource
import time
from typing import Any

from companion_core.knowledge.retrieval import B1A, B1B, B1C, RetrievalConfig, Retriever
from companion_core.semantic.model import SourceFilters

from kbench.adapters import Hit, Retrieval
from kbench.pg_env import PgCorpus, build_pg_corpus, hashing_embed_384
from kbench.scoring import percentile
from kbench.security import access_context

CONFIGS: dict[str, RetrievalConfig] = {
    "b1a": B1A,
    "b1b": B1B,
    "b1c": B1C,
    "b1a-nofilter": RetrievalConfig("B1a-nofilter", prefilter=False),
    "b1b-nofilter": RetrievalConfig("B1b-nofilter", vector=True, prefilter=False),
}


class B1Adapter:
    holdout_requires_approval = True

    def __init__(self, name: str, *, limit: int = 10, config: RetrievalConfig | None = None) -> None:
        self.name = name
        self.config = config or CONFIGS[name]
        self.limit = limit
        self.description = (
            f"{self.config.name}: PostgreSQL full-text search"
            + (" + pgvector cosine fused by reciprocal rank (k=60)" if self.config.vector else "")
            + (" + cross-encoder rerank of the authorised survivors" if self.config.rerank else "")
            + ("; access pre-filters ON" if self.config.prefilter else "; access pre-filters OFF (revalidation alone)")
            + "; every result revalidated against the stores under the case's AccessContext"
        )
        self.embedder_kind = "hashing"
        self.env: PgCorpus | None = None
        self.retriever: Retriever | None = None
        self._calls: list[dict[str, Any]] = []
        self._cpu = 0.0
        self._drops: dict[str, int] = {}

    def configure(self, embedder: str) -> None:
        self.embedder_kind = embedder

    async def load(self, built) -> None:
        if self.embedder_kind == "minilm":
            from companion_core.rag import embeddings

            embed_fn, model = embeddings.embed, embeddings._MODEL_NAME
            embed_fn(["warm up"])
        else:
            embed_fn, model = hashing_embed_384, "hashing-bag-of-words-384"
        reranker = None
        if self.config.rerank:
            from companion_core.knowledge.retrieval import CrossEncoderReranker

            reranker = CrossEncoderReranker(threads=int(os.environ.get("KNOWLEDGE_EMBED_THREADS", "2")))
            await reranker.score("warm up", ["warm up"])
        self.env = await build_pg_corpus(built.spec, embed_fn, model)
        self.retriever = Retriever(search=self.env.search, adapters=self.env.adapters, config=self.config, embed_fn=embed_fn, reranker=reranker)
        self._base_state = await self.env.fingerprint()

    async def state_fingerprint(self) -> str:
        return await self.env.fingerprint()

    async def retrieve(self, case: dict[str, Any], profile: dict[str, Any]) -> Retrieval:
        env = self.env
        access = access_context(profile)
        pinned = None
        if case.get("attached_meeting"):
            pinned = SourceFilters(pinned_sources=frozenset({("meeting", env.store_id[f"meeting:{case['attached_meeting']}"])}))
        cpu0 = time.process_time()
        result = await self.retriever.retrieve(case["question"], access, pinned, temporal=case["temporal"], limit=self.limit)
        self._cpu += time.process_time() - cpu0
        self._calls.append({**result.trace.timings_ms, "candidates": len(result.trace.candidates), "returned": len(result.bundle.items)})
        for reason, count in result.bundle.dropped.items():
            self._drops[reason] = self._drops.get(reason, 0) + count
        exposed = [Hit(env.logical_key(item.ref.key), item.text, None) for item in result.bundle.items]
        candidates = [Hit(env.logical_key(c.ref_key), "", c.score) for c in result.trace.candidates]
        return Retrieval(exposed=exposed, candidates=candidates)

    def telemetry(self) -> dict[str, Any]:
        stages = ("lexical", "embed_query", "vector", "fuse", "revalidate", "rerank")
        out: dict[str, Any] = {}
        for stage in stages:
            values = [c[stage] for c in self._calls if stage in c]
            if values:
                out[f"{stage}_ms"] = {"p50": round(percentile(values, 50), 2), "p95": round(percentile(values, 95), 2), "total": round(sum(values), 1), "n": len(values)}
        n = max(len(self._calls), 1)
        embed_total = sum(c.get("embed_query", 0.0) for c in self._calls)
        return {
            "configuration": self.config.name, "prefilter": self.config.prefilter, "queries": len(self._calls),
            "stage_latency": out,
            "python_cpu_seconds_total": round(self._cpu, 2), "python_cpu_ms_per_query": round(1000 * self._cpu / n, 2),
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
            "query_embedding_ms_per_query": round(embed_total / n, 2),
            "mean_candidates_per_query": round(sum(c["candidates"] for c in self._calls) / n, 1),
            "mean_results_per_query": round(sum(c["returned"] for c in self._calls) / n, 2),
            "revalidation_drops_by_reason": dict(sorted(self._drops.items())),
            "index_build": {"seconds": round(self.env.build_seconds, 2), "rows": self.env.index_rows},
            "note": "CPU is this Python process only (the database server's CPU is inside the wall-clock latencies, not in this figure)",
        }

    async def close(self) -> None:
        if self.env is not None:
            await self.env.close()
