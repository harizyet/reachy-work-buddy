"""Phase 44D without a database: reciprocal rank fusion, the retrieval pipeline around any search backend (lexical, hybrid, reranked),
and above all that no configuration ever returns, or hands to a reranker, anything the caller may not have. The SQL search itself is
covered in test_knowledge_retrieval_postgres.py; here the search is the in-memory double."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from companion_core.knowledge.index import InMemoryKnowledgeIndex
from companion_core.knowledge.outbox import InMemoryOutbox
from companion_core.knowledge.retrieval import (
    B1A,
    B1B,
    B1C,
    Retriever,
    reciprocal_rank_fusion,
)
from companion_core.knowledge.search import InMemorySearch, build_filter
from companion_core.knowledge.sources import build_adapters
from companion_core.knowledge.worker import IndexingWorker
from companion_core.meetings.models import MeetingJobStatus
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.semantic import access
from companion_core.semantic.model import AccessContext, SourceFilters
from companion_core.tasks.store import InMemoryTaskStore

from shared.models.response import Privacy

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def embed(texts):
    out = []
    for text in texts:
        vector = [0.0] * 64
        for word in text.lower().split():
            vector[int(hashlib.md5(word.strip(".,:").encode()).hexdigest(), 16) % 64] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        out.append([v / norm for v in vector] if norm else vector)
    return out


class World:
    def __init__(self):
        self.memory, self.meetings, self.planner = InMemoryMemoryStore(), InMemoryMeetingStore(), InMemoryPlannerStore()
        self.tasks, self.documents = InMemoryTaskStore(), InMemoryDocumentStore(embed_fn=embed)
        self.adapters = build_adapters(memory=self.memory, documents=self.documents, meetings=self.meetings, planner=self.planner,
                                       tasks=self.tasks, clock=lambda: T0)
        self.index, self.outbox = InMemoryKnowledgeIndex(), InMemoryOutbox()
        self.worker = IndexingWorker(adapters=self.adapters, index=self.index, outbox=self.outbox, embed_fn=embed,
                                     embedding_model="t", clock=lambda: T0)
        self.search = InMemorySearch(self.index)

    def retriever(self, config, **kw):
        return Retriever(search=self.search, adapters=self.adapters, config=config, embed_fn=embed, clock=lambda: T0, **kw)

    async def meeting(self, texts, *, scope=None, sensitivity=Privacy.WORK_PRIVATE):
        m = await self.meetings.create_meeting(title="Sync", audio=b"x", source_filename="a.wav", content_type="audio/wav",
                                               project_scope=scope, sensitivity=sensitivity)
        self.meetings._touch(
            m, transcript_segments=[{"start": float(i), "end": float(i + 1), "text": t} for i, t in enumerate(texts)],
            diarization_segments=[{"start": float(i), "end": float(i + 1), "speaker": "SPEAKER_00"} for i in range(len(texts))],
            status=MeetingJobStatus.ALIGNING,
        )
        await self.meetings.set_speaker_names(m.id, {"SPEAKER_00": "Priya"})
        return m.id

    async def build(self):
        for source_type, adapter in self.adapters.items():
            for sid in await adapter.list_ids():
                await self.worker.sync_source(source_type, sid)


def ctx(**kw):
    return AccessContext(**{"principal": "o", "sensitivity_ceiling": Privacy.WORK_PRIVATE, **kw})


def run(coro):
    return asyncio.run(coro)


class RecordingReranker:
    def __init__(self, prefer=None):
        self.seen: list[str] = []
        self.prefer = prefer

    async def score(self, query, texts):
        self.seen.extend(texts)
        return [10.0 if self.prefer and self.prefer in t else float(-i) for i, t in enumerate(texts)]


# ---- fusion -----------------------------------------------------------------------------------------------------

def test_reciprocal_rank_fusion_rewards_agreement_and_breaks_ties_stably() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])
    assert [k for k, _ in fused] == ["b", "a", "c"]  # b is in both lists, so it beats a, which was first in one only
    scores = dict(fused)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61) and scores["a"] == pytest.approx(1 / 61) and scores["c"] == pytest.approx(1 / 62)
    assert reciprocal_rank_fusion([["z", "y"]], k=60)[0][0] == "z"
    assert reciprocal_rank_fusion([["b"], ["a"]]) == reciprocal_rank_fusion([["b"], ["a"]])
    assert [k for k, _ in reciprocal_rank_fusion([["b"], ["a"]])] == ["a", "b"]  # equal scores: by key, not by chance
    assert reciprocal_rank_fusion([]) == [] and reciprocal_rank_fusion([[], []]) == []


def test_the_search_filter_encodes_the_callers_access_and_only_narrows() -> None:
    cloud = ctx(destinations=frozenset({"local", "cloud"}), project_scopes=frozenset({"harbor"}))
    flt = build_filter(cloud, SourceFilters(source_types=frozenset({"note"})), temporal="current")
    assert flt.sensitivities == ("public", "work-private") and flt.scopes == ("harbor",) and flt.exclude_local_only
    assert flt.source_types == ("note",) and flt.current_only and flt.pinned is None
    local = build_filter(ctx(), None, temporal="include_historical")
    assert not local.exclude_local_only and local.scopes is None and not local.current_only
    assert build_filter(ctx(sensitivity_ceiling=Privacy.PUBLIC), None, temporal="current").sensitivities == ("public",)
    off = build_filter(cloud, None, temporal="current", prefilter=False)
    assert off.sensitivities is None and off.scopes is None and not off.exclude_local_only
    pinned = SourceFilters(pinned_sources=frozenset({("meeting", "m1")}))
    assert build_filter(ctx(), pinned, temporal="current", pinned_only=True).pinned == (("meeting", "m1"),)
    assert build_filter(ctx(), pinned, temporal="current").pinned is None


# ---- the pipeline -----------------------------------------------------------------------------------------------

async def corpus():
    w = World()
    await w.memory.add_memory(content="Harbor default model is Falcon-7B", source="s", project_scope="harbor")
    await w.memory.add_memory(content="Tomas performance review is on Friday", source="s", sensitivity=Privacy.SENSITIVE)
    await w.planner.add_note("Actions", "Tomas benchmarks Falcon-7B latency by Thursday", project_scope="harbor")
    await w.planner.add_note("Lantern checklist", "update the rollback script", project_scope="lantern")
    await w.tasks.add_task("Send Priya the Harbor summary", project_scope="harbor")
    await w.documents.ingest_document(title="Architecture", content="# Queue\nfailed jobs retry five times\n\n# Model\nfalcon runs on the gpu host", source="s", project_scope="harbor")
    mid = await w.meeting(["we keep falcon as the default model", "retries are five"], scope="harbor")
    await w.build()
    return w, mid


def keys(result):
    return [i.ref.key for i in result.bundle.items]


def test_lexical_and_hybrid_find_the_relevant_parts_and_report_their_trace() -> None:
    async def go():
        w, _ = await corpus()
        for config in (B1A, B1B):
            result = await w.retriever(config).retrieve("what is the default falcon model", ctx())
            kinds = {i.ref.source_type for i in result.bundle.items}
            assert {"memory", "meeting"} <= kinds and result.bundle.dropped == {}
            trace = result.trace
            assert trace.config == config.name and trace.candidates and "revalidate" in trace.timings_ms and "lexical" in trace.timings_ms
            assert ("vector" in trace.timings_ms) == config.vector and (trace.query_embedding_ms > 0) == config.vector
            assert trace.candidates[0].fused_rank == 1 and trace.candidates[0].lexical_rank is not None
        hybrid = await w.retriever(B1B).retrieve("falcon gpu", ctx())
        assert any(c.vector_rank is not None and c.lexical_rank is not None for c in hybrid.trace.candidates)

    run(go())


@pytest.mark.parametrize("config", [B1A, B1B, B1C])
def test_no_configuration_returns_what_the_caller_may_not_have(config) -> None:
    async def go():
        w, _ = await corpus()
        rerank = RecordingReranker() if config.rerank else None
        retriever = w.retriever(config, reranker=rerank)
        query = "tomas review friday falcon rollback latency retries"
        for caller in (ctx(), ctx(sensitivity_ceiling=Privacy.PUBLIC), ctx(project_scopes=frozenset({"lantern"})),
                       ctx(destinations=frozenset({"local", "cloud"})), access.access_for_owner("o", channel_private=False)):
            result = await retriever.retrieve(query, caller)
            for item in result.bundle.items:
                assert access.decide(caller, item) is None, (config.name, item.ref.key)
        sensitive = (await retriever.retrieve(query, ctx())).bundle
        assert all("review" not in i.text for i in sensitive.items)  # work-private ceiling: the sensitive memory never appears
        if rerank:
            assert not any("review" in t for t in rerank.seen)  # nor is its text ever handed to the reranker
            shared = RecordingReranker()
            await w.retriever(config, reranker=shared).retrieve(query, ctx(destinations=frozenset({"cloud"})))
            assert not any("Priya:" in t or "we keep falcon" in t for t in shared.seen)  # meeting speech never reaches a cloud-capable caller's reranker

    run(go())


@pytest.mark.parametrize("prefilter", [True, False])
def test_revalidation_alone_keeps_a_stale_index_safe_even_with_the_prefilter_off(prefilter) -> None:
    """The index labels lag the sources here; the search proposes everything; only revalidation stands between the caller and the data."""

    async def go():
        w, mid = await corpus()
        notes = await w.planner.list_notes()
        secret = next(n for n in notes if n.project_scope == "harbor")
        w.planner._notes[secret.id].sensitivity = Privacy.SENSITIVE  # raised in the source after indexing
        mem = (await w.memory.list_memories())[0]
        await w.memory.forget(mem.id)  # forgotten after indexing, index not yet updated
        await w.meetings.cancel_meeting(mid)
        config = type(B1B)(**{**B1B.__dict__, "prefilter": prefilter, "name": "B1b-test"})
        result = await w.retriever(config).retrieve("falcon tomas benchmarks default model retries five", ctx())
        returned = keys(result)
        assert f"note:{secret.id}" not in returned and f"memory:{mem.id}" not in returned
        assert not any(k.startswith(f"meeting:{mid}") for k in returned)
        if not prefilter:  # with the pre-filter off, those candidates were proposed and then dropped, and the drops are counted
            assert {"over_ceiling", "forgotten", "deleted"} <= set(result.bundle.dropped)
            assert any(c.ref_key == f"note:{secret.id}" for c in result.trace.candidates)

    run(go())


def test_the_returned_text_comes_from_the_source_not_the_index() -> None:
    async def go():
        w, _ = await corpus()
        note = next(n for n in await w.planner.list_notes() if "Thursday" in n.body)
        await w.planner.update_note(note.id, "Actions", "Dana now benchmarks it on Monday")  # index not rebuilt
        result = await w.retriever(B1A).retrieve("benchmarks falcon thursday", ctx())
        item = next(i for i in result.bundle.items if i.ref.key == f"note:{note.id}")
        assert "Dana" in item.text and "Thursday" not in item.text

    run(go())


def test_limit_order_and_determinism() -> None:
    async def go():
        w, _ = await corpus()
        retriever = w.retriever(B1B)
        a = await retriever.retrieve("falcon", ctx(), limit=3)
        b = await retriever.retrieve("falcon", ctx(), limit=3)
        assert keys(a) == keys(b) and len(a.bundle.items) == 3
        assert [c.ref_key for c in a.trace.candidates] == [c.ref_key for c in b.trace.candidates]
        wide = await retriever.retrieve("falcon", ctx(), limit=50)
        assert keys(wide)[:3] == keys(a)

    run(go())


def test_empty_stopword_and_odd_queries_are_handled() -> None:
    async def go():
        w, _ = await corpus()
        for config in (B1A, B1B):
            retriever = w.retriever(config)
            for query in ("", "   ", "what is the", "'; DROP TABLE knowledge_items; --", "a & | ! (b)", "x" * 5000):
                result = await retriever.retrieve(query, ctx())
                assert isinstance(result.bundle.items, list)
        assert (await w.index.count()) > 0

    run(go())


def test_pinned_sources_are_always_candidates_but_gain_no_access() -> None:
    async def go():
        w, mid = await corpus()
        other = await w.meeting(["secret strategy talk about acquisitions"], scope="harbor", sensitivity=Privacy.SENSITIVE)
        await w.worker.sync_source("meeting", other)
        pin = SourceFilters(pinned_sources=frozenset({("meeting", mid)}))
        plain = await w.retriever(B1A).retrieve("keep", ctx(), pin, limit=1)
        assert keys(plain)[0].startswith(f"meeting:{mid}")
        trace = plain.trace.candidates[0]
        assert trace.pinned_rank is not None
        # pinning a source the caller may not see changes nothing about what they are allowed to see
        pin_secret = SourceFilters(pinned_sources=frozenset({("meeting", other)}))
        result = await w.retriever(B1B).retrieve("secret strategy acquisitions", ctx(), pin_secret)
        assert not any(k.startswith(f"meeting:{other}") for k in keys(result))

    run(go())


def test_the_contract_call_applies_a_token_budget_and_counts_what_it_cuts() -> None:
    async def go():
        w, _ = await corpus()
        retriever = w.retriever(B1A)
        full = await retriever("falcon model retries", ctx())
        assert len(full.items) >= 3
        small = await retriever("falcon model retries", ctx(), None, 12)
        assert 0 < len(small.items) < len(full.items) and small.dropped.get("budget") == len(full.items) - len(small.items)
        assert small.token_estimate <= 12

    run(go())


def test_reranking_reorders_only_the_authorised_survivors() -> None:
    async def go():
        w, _ = await corpus()
        base = await w.retriever(B1B).retrieve("falcon", ctx(), limit=5)
        wanted = keys(base)[-1]
        target_text = next(i.text for i in base.bundle.items if i.ref.key == wanted)
        reranked = await w.retriever(B1C, reranker=RecordingReranker(prefer=target_text[:20])).retrieve("falcon", ctx(), limit=5)
        assert keys(reranked)[0] == wanted and set(keys(reranked)) == set(keys(base))
        assert reranked.trace.timings_ms["rerank"] >= 0

    run(go())


def test_a_configuration_without_what_it_needs_is_refused() -> None:
    w = World()
    with pytest.raises(ValueError):
        Retriever(search=w.search, adapters=w.adapters, config=B1B, embed_fn=None)
    with pytest.raises(ValueError):
        Retriever(search=w.search, adapters=w.adapters, config=B1C, embed_fn=embed, reranker=None)


def test_historical_mode_reaches_the_prefilter_and_revalidation() -> None:
    async def go():
        w = World()
        m = await w.memory.add_memory(content="falcon freeze window", source="s", expires_at=T0 + timedelta(days=1))
        await w.build()
        row = w.index.rows[f"memory:{m.id}"]
        w.index.rows[row.ref_key] = type(row)(**{**row.__dict__, "valid_until": T0 - timedelta(days=1)})
        current = await w.retriever(B1A).retrieve("falcon freeze", ctx())
        historical = await w.retriever(B1A).retrieve("falcon freeze", ctx(), temporal="include_historical")
        assert current.bundle.items == [] and not current.trace.candidates  # the prefilter excluded the lapsed row
        assert historical.trace.candidates  # the historical mode searched it (the source, which is authoritative, still allows it)

    run(go())
