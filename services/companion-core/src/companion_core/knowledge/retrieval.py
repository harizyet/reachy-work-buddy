"""Retrieval over the knowledge index (Phase 44D): lexical search, optional vector search fused by reciprocal rank, optional reranking.

Every configuration ends in `revalidate`, the retrieval-time check against the authoritative stores, under the caller's trusted
AccessContext. The search stages only propose candidates; whatever they propose, a result is returned only if its source still exists,
is visible, and the caller may see it, and its text is read from the source. Reranking, when enabled, runs *after* revalidation, so the
reranker never sees text the caller is not allowed to have.

Nothing here is wired into a route, the conversation path or any flag: this is a library that the benchmark exercises (44D) and that
the context builder will call (44E, behind its own approval).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from companion_core.knowledge.revalidate import Candidate, revalidate
from companion_core.knowledge.search import SearchBackend, SearchHit, build_filter
from companion_core.knowledge.sources import SourceAdapter
from companion_core.semantic.model import (
    AccessContext,
    ContextBundle,
    SourceFilters,
    SourceRef,
)

MAX_QUERY_CHARS = 1000
RRF_K = 60  # the constant from the original reciprocal rank fusion paper; it damps the advantage of a single first place


@dataclass(frozen=True)
class RetrievalConfig:
    name: str
    vector: bool = False  # fuse a vector leg with the lexical one
    rerank: bool = False  # reorder the authorised survivors with a cross-encoder
    limit: int = 10  # items returned
    candidates: int = 40  # per search leg
    prefilter: bool = True  # narrow the search by the caller's access using the index's labels (revalidation always applies)
    rrf_k: int = RRF_K
    rerank_pool: int = 20  # survivors handed to the reranker


B1A = RetrievalConfig("B1a")
B1B = RetrievalConfig("B1b", vector=True)
B1C = RetrievalConfig("B1c", vector=True, rerank=True)


class Reranker(Protocol):
    async def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


@dataclass(frozen=True)
class CandidateTrace:
    ref_key: str
    fused_rank: int
    lexical_rank: int | None
    vector_rank: int | None
    pinned_rank: int | None
    score: float


@dataclass
class RetrievalTrace:
    config: str
    candidates: list[CandidateTrace] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    survivors_before_limit: int = 0
    query_embedding_ms: float = 0.0


@dataclass
class RetrievalResult:
    bundle: ContextBundle
    trace: RetrievalTrace


def reciprocal_rank_fusion(lists: Sequence[Sequence[str]], *, k: int = RRF_K) -> list[tuple[str, float]]:
    """Each key scores the sum over the lists it appears in of 1 / (k + its rank in that list, starting at 1). Ties break by key so
    the order is the same on every run."""
    scores: dict[str, float] = {}
    for ranked in lists:
        for rank, key in enumerate(ranked, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _ref(key: str) -> SourceRef:
    source_type, _, rest = key.partition(":")
    source_id, _, locator = rest.partition("#")
    return SourceRef(source_type=source_type, source_id=source_id, locator=locator or None)  # type: ignore[arg-type]


class Retriever:
    def __init__(
        self,
        *,
        search: SearchBackend,
        adapters: dict[str, SourceAdapter],
        config: RetrievalConfig,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
        reranker: Reranker | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if config.vector and embed_fn is None:
            raise ValueError(f"{config.name} needs an embedder")
        if config.rerank and reranker is None:
            raise ValueError(f"{config.name} needs a reranker")
        self.search, self.adapters, self.config = search, adapters, config
        self.embed_fn, self.reranker, self.clock = embed_fn, reranker, clock

    async def retrieve(
        self,
        query: str,
        access: AccessContext,
        source_filters: SourceFilters | None = None,
        *,
        temporal: Literal["current", "include_historical"] = "current",
        limit: int | None = None,
    ) -> RetrievalResult:
        cfg, limit = self.config, limit or self.config.limit
        query = query.replace("\x00", " ")[:MAX_QUERY_CHARS]  # Postgres text cannot hold NUL; a very long query only costs time
        trace = RetrievalTrace(config=cfg.name)
        clock = time.perf_counter
        flt = build_filter(access, source_filters, temporal=temporal, prefilter=cfg.prefilter)
        pinned = source_filters is not None and bool(source_filters.pinned_sources)
        pflt = build_filter(access, source_filters, temporal=temporal, prefilter=cfg.prefilter, pinned_only=True) if pinned else None

        t = clock()
        lexical = await self.search.lexical(query, flt, cfg.candidates)
        pinned_lexical = await self.search.lexical(query, pflt, 5) if pflt else []
        trace.timings_ms["lexical"] = (clock() - t) * 1000

        vector: list[SearchHit] = []
        pinned_vector: list[SearchHit] = []
        if cfg.vector and query.strip():
            t = clock()
            (embedding,) = await asyncio.to_thread(self.embed_fn, [query])
            trace.query_embedding_ms = (clock() - t) * 1000
            trace.timings_ms["embed_query"] = trace.query_embedding_ms
            t = clock()
            vector = await self.search.vector(embedding, flt, cfg.candidates)
            pinned_vector = await self.search.vector(embedding, pflt, 5) if pflt else []
            trace.timings_ms["vector"] = (clock() - t) * 1000

        t = clock()
        lists = [[h.ref_key for h in lexical], [h.ref_key for h in vector]]
        if pinned:
            lists.append(_merge_pinned(pinned_lexical, pinned_vector))
        fused = reciprocal_rank_fusion([lst for lst in lists if lst], k=cfg.rrf_k)
        rank_in = [{key: r for r, key in enumerate(lst, 1)} for lst in lists]
        trace.candidates = [
            CandidateTrace(
                key, i, rank_in[0].get(key), rank_in[1].get(key), rank_in[2].get(key) if pinned else None, score
            )
            for i, (key, score) in enumerate(fused, 1)
        ]
        trace.timings_ms["fuse"] = (clock() - t) * 1000

        # Revalidate more than `limit` (some will be dropped), preserving the fused order.
        t = clock()
        pool = [Candidate(_ref(key)) for key, _ in fused[: max(limit * 3, cfg.rerank_pool)]]
        bundle = await revalidate(pool, access, self.adapters, temporal=temporal, now=self.clock())
        trace.timings_ms["revalidate"] = (clock() - t) * 1000
        trace.survivors_before_limit = len(bundle.items)

        items = list(bundle.items)
        if cfg.rerank and items:
            t = clock()
            head = items[: cfg.rerank_pool]
            scores = await self.reranker.score(query, [i.text for i in head])
            order = sorted(range(len(head)), key=lambda i: (-scores[i], i))
            items = [head[i] for i in order] + items[cfg.rerank_pool :]
            trace.timings_ms["rerank"] = (clock() - t) * 1000
        items = items[:limit]
        bundle = ContextBundle(
            items=items, dropped=bundle.dropped,
            max_sensitivity=bundle.max_sensitivity if len(items) == len(bundle.items) else _max_sensitivity(items),
            local_only=any(i.local_only for i in items), token_estimate=sum(max(1, len(i.text) // 4) for i in items),
        )
        return RetrievalResult(bundle, trace)

    async def __call__(
        self,
        query: str,
        access: AccessContext,
        source_filters: SourceFilters | None = None,
        token_budget: int | None = None,
        *,
        temporal: Literal["current", "include_historical"] = "current",
    ) -> ContextBundle:
        """The `ContextRetriever` contract from 44A. Token budgeting belongs to the context builder (44E); here it only caps the count
        of items when given, by the estimate already on the bundle."""
        result = await self.retrieve(query, access, source_filters, temporal=temporal)
        bundle = result.bundle
        if token_budget is None:
            return bundle
        kept, used = [], 0
        for item in bundle.items:
            cost = max(1, len(item.text) // 4)
            if used + cost > token_budget:
                break
            kept.append(item)
            used += cost
        dropped = dict(bundle.dropped)
        if len(kept) < len(bundle.items):
            dropped["budget"] = len(bundle.items) - len(kept)
        return ContextBundle(items=kept, dropped=dropped, max_sensitivity=_max_sensitivity(kept),
                             local_only=any(i.local_only for i in kept), token_estimate=used)


def _merge_pinned(lexical: Sequence[SearchHit], vector: Sequence[SearchHit]) -> list[str]:
    return [key for key, _ in reciprocal_rank_fusion([[h.ref_key for h in lexical], [h.ref_key for h in vector]])][:5]


def _max_sensitivity(items):
    from companion_core.semantic import access as rules
    from shared.models.response import Privacy

    return rules.effective_sensitivity(Privacy.PUBLIC, *(i.sensitivity for i in items))


class CrossEncoderReranker:
    """sentence-transformers CrossEncoder, loaded on first use and run in a worker thread. Only authorised text is ever passed in."""

    MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, model_name: str | None = None, threads: int = 2) -> None:
        self.model_name, self.threads, self._model = model_name or self.MODEL, threads, None

    def _load(self):
        if self._model is None:
            import torch
            from sentence_transformers import CrossEncoder

            torch.set_num_threads(self.threads)
            self._model = CrossEncoder(self.model_name)
        return self._model

    async def score(self, query: str, texts: Sequence[str]) -> list[float]:
        def run():
            return [float(s) for s in self._load().predict([(query, t) for t in texts])]

        return await asyncio.to_thread(run)
