"""Phase 31 on real PostgreSQL (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector): migration 032 and its rollback script, the structural guarantees, the real
store under concurrency and crash recovery, and the whole flow (analyse with a scripted model, review, task, then the Phase 44 index and an authorised retrieval) over the real
stores. Synthetic data only."""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from companion_core.knowledge.index import PostgresKnowledgeIndex
from companion_core.knowledge.outbox import PostgresOutbox
from companion_core.knowledge.retrieval import B1B, Retriever
from companion_core.knowledge.search import PostgresSearch
from companion_core.knowledge.sources import build_adapters
from companion_core.knowledge.worker import IndexingWorker
from companion_core.meeting_analysis.models import (
    Evidence,
    Item,
    ItemKind,
    ItemStatus,
    Run,
    Seg,
    action_record_id,
    item_fingerprint,
)
from companion_core.meeting_analysis.postgres_store import PostgresMeetingAnalysisStore
from companion_core.meeting_analysis.service import MeetingAnalysisService
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.migrations.__main__ import upgrade
from companion_core.notepad_processing.models import content_hash
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.secrets import Keyring
from companion_core.semantic import access
from companion_core.tasks.postgres_store import PostgresTaskStore
from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

from shared.models.response import Privacy

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
KEYS = Keyring("one", {"one": b"\x01" * 32})
ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-032.sql"
ROLLBACK_033 = ROLLBACK.with_name("rollback-033.sql")  # the head is 033 now (calendar feed): the runbook undoes it first
NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
TEXTS = ["Let's fix the migration date.", "Agreed, we will migrate the cluster in the first week of November.", "Alice will contact the vendor about compatibility by Friday."]


def embed(texts):
    out = []
    for text in texts:
        vector = [0.0] * 384
        for word in text.lower().split():
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        out.append([v / norm for v in vector] if norm else vector)
    return out


@pytest.fixture
def dsn():
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "test_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    url = psycopg.conninfo.make_conninfo(root, dbname=name)
    upgrade(url, KEYS)
    try:
        yield url
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def sql(dsn, query, params=None):
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def run_of(meeting_id="m1", **over):
    segs = [Seg(index=i, start=60.0 * i, end=60.0 * i + 50, text=t, speaker="Speaker 1") for i, t in enumerate(TEXTS)]
    base = {"meeting_id": meeting_id, "meeting_title": "Sync", "transcript_hash": content_hash("t"), "segments": segs, "timezone": "UTC", "sensitivity": Privacy.WORK_PRIVATE,
            "inputs_hash": content_hash("t|v"), "created_at": NOW}
    base.update(over)
    return Run(**base)


def item_of(run, quote, kind=ItemKind.ACTION, segment=2, **over):
    base = {"run_id": run.id, "meeting_id": run.meeting_id, "transcript_hash": run.transcript_hash, "kind": kind, "text": quote[:40],
            "evidence": [Evidence(segment=segment, start=60.0 * segment, end=60.0 * segment + 50, speaker="Speaker 1", quote=quote)],
            "status": ItemStatus.PENDING if kind is ItemKind.ACTION else ItemStatus.NOTED, "fingerprint": item_fingerprint(kind, quote), "sensitivity": Privacy.WORK_PRIVATE,
            "created_at": NOW}
    base.update(over)
    return Item(**base)


# ---- migration 032 ------------------------------------------------------------------------------------------------------------------------------

def test_the_migration_creates_only_bookkeeping_and_one_trigger_into_the_existing_outbox(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("033_calendar_feed",)]
    assert {r[0] for r in sql(dsn, "SELECT tablename FROM pg_tables WHERE tablename LIKE 'meeting_analysis_%'")} == {"meeting_analysis_runs", "meeting_analysis_items"}
    for table in ("meeting_analysis_runs", "meeting_analysis_items"):
        assert sql(dsn, f"SELECT count(*) FROM pg_constraint WHERE conrelid = '{table}'::regclass AND contype = 'f'") == [(0,)]  # no key into meetings or tasks
    assert sql(dsn, "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'meeting_analysis_runs'::regclass AND NOT tgisinternal") == [(0,)]
    assert sql(dsn, "SELECT tgname FROM pg_trigger WHERE tgrelid = 'meeting_analysis_items'::regclass AND NOT tgisinternal") == [("meeting_analysis_knowledge",)]
    upgrade(dsn, KEYS)  # a repeat changes nothing


def test_structural_guarantees_one_active_run_one_item_per_sentence_and_no_item_without_evidence(dsn):
    async def go():
        store = await PostgresMeetingAnalysisStore.connect(dsn)
        try:
            first, created = await store.enqueue(run_of(), force=False)
            assert created
            for _ in range(3):
                again, created = await store.enqueue(run_of(), force=True)  # even a forced request cannot start a second active run
                assert not created and again.id == first.id
        finally:
            await store.close()

    asyncio.run(go())
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, "INSERT INTO meeting_analysis_items (id, run_id, meeting_id, transcript_hash, kind, text, evidence, status, fingerprint, prompt_version, sensitivity, created_at) "
                 "VALUES ('i','r','m','h','decision','t','[]','noted','f','v','work-private',now())")  # no evidence, no item
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, "INSERT INTO meeting_analysis_items (id, run_id, meeting_id, transcript_hash, kind, text, evidence, status, fingerprint, prompt_version, sensitivity, created_at) "
                 "VALUES ('i','r','m','h','plan','t','[{}]','noted','f','v','work-private',now())")


def test_the_rollback_script_removes_only_the_analysis_and_the_migration_applies_again(dsn):
    sql(dsn, "INSERT INTO tasks (id, text, status, created_at) VALUES ('t1','confirmed from a meeting','open',now())")
    sql(dsn, "INSERT INTO meetings (id, title, source_filename, content_type, audio_path, status) VALUES ('m1','x','a','b','c','complete')")
    sql(dsn, "INSERT INTO meeting_analysis_items (id, run_id, meeting_id, transcript_hash, kind, text, evidence, status, fingerprint, prompt_version, sensitivity, record_id, created_at) "
             "VALUES ('i','r','m1','h','action','t','[{\"segment\": 0}]','accepted','f','v','work-private','t1',now())")
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK_033.read_text())
        conn.execute(ROLLBACK.read_text())  # one transaction, as the script's own instructions require
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("031_documents",)]
    assert sql(dsn, "SELECT count(*) FROM pg_tables WHERE tablename LIKE 'meeting_analysis_%'") == [(0,)]
    assert sql(dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'meeting_analysis_knowledge_trg'") == [(0,)]
    assert sql(dsn, "SELECT text FROM tasks") == [("confirmed from a meeting",)] and sql(dsn, "SELECT count(*) FROM meetings") == [(1,)]  # authoritative data stays
    sql(dsn, "UPDATE meetings SET title = 'y'")  # the meetings trigger still works without ours
    upgrade(dsn, KEYS)
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("033_calendar_feed",)] and sql(dsn, "SELECT count(*) FROM meeting_analysis_items") == [(0,)]


# ---- the real store -----------------------------------------------------------------------------------------------------------------------------

def test_lease_takeover_dedupe_and_atomic_completion_on_the_real_store(dsn):
    async def go():
        store = await PostgresMeetingAnalysisStore.connect(dsn)
        try:
            r, _ = await store.enqueue(run_of(), force=False)
            claimed = await store.claim_next(NOW)
            assert claimed.id == r.id and claimed.attempts == 1
            assert await store.claim_next(NOW + timedelta(seconds=5)) is None  # leased
            again = await store.claim_next(NOW + timedelta(seconds=5000))  # the runner died: lease expired
            assert again.id == r.id and again.attempts == 2
            batch = [item_of(r, TEXTS[2]), item_of(r, TEXTS[1], ItemKind.DECISION, 1), item_of(r, TEXTS[2])]  # a duplicate sentence in one batch
            assert await store.complete_run(r.id, batch, model="m", rejected={"no_evidence_in_source": 2}, now=NOW) == 2
            assert await store.complete_run(r.id, batch, model="m", rejected={}, now=NOW) == 0  # a second completion adds nothing
            done = await store.get_run(r.id)
            assert done.status.value == "succeeded" and done.item_count == 2 and done.rejected == {"no_evidence_in_source": 2} and len(done.segments) == 3
            same, created = await store.enqueue(run_of(), force=False)  # unchanged inputs: answered by the finished run
            assert not created and same.id == r.id
            second, created = await store.enqueue(run_of(), force=True)
            assert created
            await store.claim_next(NOW)
            assert await store.complete_run(second.id, [item_of(second, TEXTS[2])], model="m", rejected={}, now=NOW) == 0  # nothing resurfaces
            action = next(i for i in await store.list_items(meeting_id="m1") if i.kind is ItemKind.ACTION)
            assert (await store.dismiss(action.id, now=NOW)).outcome == "done"
            third, _ = await store.enqueue(run_of(), force=True)
            await store.claim_next(NOW)
            assert await store.complete_run(third.id, [item_of(third, TEXTS[2])], model="m", rejected={}, now=NOW) == 0  # not even a dismissed one
            order = [i.kind.value for i in await store.list_items(meeting_id="m1")]
            assert order == ["decision", "action"]  # transcript order
        finally:
            await store.close()

    asyncio.run(go())
    assert sql(dsn, "SELECT count(*) FROM meeting_analysis_items") == [(2,)]


def test_concurrent_accepts_claim_once_and_a_stale_claim_is_taken_over(dsn):
    async def go():
        store = await PostgresMeetingAnalysisStore.connect(dsn)
        try:
            r, _ = await store.enqueue(run_of(), force=False)
            await store.claim_next(NOW)
            await store.complete_run(r.id, [item_of(r, TEXTS[2])], model="m", rejected={}, now=NOW)
            item = (await store.list_items(meeting_id="m1"))[0]
            outcomes = await asyncio.gather(*[store.claim_accept(item.id, text="t", sensitivity=Privacy.WORK_PRIVATE, edited=False, now=NOW) for _ in range(8)])
            assert sorted(o.outcome for o in outcomes) == ["claimed"] + ["in_progress"] * 7
            assert await store.stale_accepting(NOW) == [] and await store.stale_accepting(NOW + timedelta(minutes=10)) == [item.id]
            taken = await store.claim_accept(item.id, text="ignored", sensitivity=Privacy.WORK_PRIVATE, edited=False, now=NOW + timedelta(minutes=10))
            assert taken.outcome == "claimed" and taken.item.final_text == "t"  # the values stored at the first claim win
            done = await store.finish_accept(item.id, "task", "t-1", now=NOW)
            assert done.record_id == "t-1" and (await store.item_for_record("t-1")).id == item.id
            assert (await store.finish_accept(item.id, "task", "other", now=NOW)).record_id == "t-1"  # finishing twice changes nothing
            assert (await store.dismiss(item.id, now=NOW)).outcome == "closed"
        finally:
            await store.close()

    asyncio.run(go())


# ---- the whole flow over the real stores ----------------------------------------------------------------------------------------------------

def test_analyse_review_task_and_authorised_retrieval_over_the_real_stores(dsn, tmp_path):
    async def go():
        memory, planner, tasks = await PostgresMemoryStore.connect(dsn), await PostgresPlannerStore.connect(dsn), await PostgresTaskStore.connect(dsn)
        documents, meetings = await PostgresDocumentStore.connect(dsn, embed_fn=embed), await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        analysis, index, outbox = await PostgresMeetingAnalysisStore.connect(dsn), await PostgresKnowledgeIndex.connect(dsn), await PostgresOutbox.connect(dsn)
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        adapters = build_adapters(memory=memory, documents=documents, meetings=meetings, planner=planner, tasks=tasks, meeting_analysis=lambda: analysis)
        worker = IndexingWorker(adapters=adapters, index=index, outbox=outbox, embed_fn=embed, embedding_model="test-model")
        try:
            m = await meetings.create_meeting(title="Cluster sync", audio=b"x", source_filename="a.wav", content_type="audio/wav", sensitivity=Privacy.WORK_PRIVATE,
                                               started_at=datetime(2026, 10, 9, 14, 0, tzinfo=UTC))
            segments = [{"start": 60.0 * i, "end": 60.0 * i + 50, "text": t} for i, t in enumerate(TEXTS)]
            sql(dsn, "UPDATE meetings SET transcript_segments = %s, diarization_segments = %s, status = 'complete' WHERE id = %s",
                (Json(segments), Json([{"start": s["start"], "end": s["end"], "speaker": "SPEAKER_00"} for s in segments]), m.id))
            scripted = json.dumps({"items": [
                {"type": "decision", "text": "Migrate in the first week of November", "evidence": [{"segment": 1, "quote": "we will migrate the cluster in the first week of November"}]},
                {"type": "action", "text": "Contact the vendor about compatibility", "evidence": [{"segment": 2, "quote": "Alice will contact the vendor about compatibility by Friday"}],
                 "assignee": "Alice", "stated_time": "by Friday"},
            ]})

            async def provider():
                async def ask(messages, max_tokens):
                    return scripted

                return ask, "scripted-7b"

            async def tz():
                return "UTC"

            service = MeetingAnalysisService(analysis, meetings, tasks, planner, tz, provider=provider)
            queued = await service.enqueue(m.id)
            assert queued["created"] and await service.process_next()
            await worker.drain()
            query = "when do we migrate the cluster"
            owner = access.access_for_owner("o", channel_private=True)
            retriever = Retriever(search=PostgresSearch(pool), adapters=adapters, config=B1B, embed_fn=embed)

            async def found():
                result = await retriever.retrieve(query + " vendor compatibility Alice", owner)
                return {i.ref.locator: i for i in result.bundle.items if i.ref.source_type == "meeting"}

            first = await found()
            assert not any(k.startswith("analysis:") for k in first)  # a decision and a pending action are unreviewed: nothing from the analysis is offered to retrieval
            assert "1" in first and "2" in first  # the source segments stay retrievable
            # authorisation is Phase 44's: a public-only caller and a robot-room (non-private) caller see no finding or segment of a work-private meeting
            for narrow in (access.access_for_owner("o", channel_private=False), access.narrowed(owner, sensitivity_ceiling=Privacy.PUBLIC)):
                assert not [i for i in (await retriever.retrieve(query, narrow)).bundle.items if i.ref.source_type == "meeting"]
            # confirm the action: it becomes a task and, after the outbox runs, retrievable with its evidence stamp, marked as generated
            pending = (await service.pending())["items"]
            assert len(pending) == 1
            confirmed = await service.accept(pending[0]["id"])
            assert confirmed["record"]["id"] == action_record_id(pending[0]["id"]) and [t.id for t in await tasks.list_tasks()] == [confirmed["record"]["id"]]
            await worker.drain()
            offered = {k: i for k, i in (await found()).items() if k.startswith("analysis:")}
            assert [i.text for i in offered.values()] == ["Action: Contact the vendor about compatibility. Assigned to: Alice. Evidence at [2:00]."]
            assert all(i.provenance.authority == "model_generated" for i in offered.values())
            # dismissing the decision changes nothing in the index (it was never in it)
            decision = next(i for i in await analysis.list_items(meeting_id=m.id) if i.kind is ItemKind.DECISION)
            await service.dismiss(decision.id)
            await worker.drain()
            assert {k for k in await found() if k.startswith("analysis:")} == set(offered)
            # the meeting and its analysis are one source: deleting the meeting leaves nothing indexed
            await service.meeting_deleted(m.id)
            await meetings.delete_meeting(m.id)
            await worker.drain()
            assert sql(dsn, "SELECT count(*) FROM knowledge_items WHERE source_type = 'meeting'") == [(0,)]
            assert len(await tasks.list_tasks()) == 1  # the owner's task stays
        finally:
            await pool.close()
            for part in (memory, planner, tasks, documents, meetings, analysis, index, outbox):
                await part.close()

    asyncio.run(go())


def test_reanalysis_refreshes_undecided_items_leaves_decided_ones_and_keeps_distinct_findings_apart(dsn):
    async def go():
        store = await PostgresMeetingAnalysisStore.connect(dsn)
        try:
            r, _ = await store.enqueue(run_of(), force=False)
            await store.claim_next(NOW)
            mail, update = "Alice will email the vendor", "Bob will update the schedule document"
            assert await store.complete_run(r.id, [item_of(r, mail, segment=0), item_of(r, update, segment=0)], model="m", rejected={}, now=NOW) == 2  # two findings, one segment
            a, b = (await store.list_items(meeting_id="m1"))
            await store.claim_accept(b.id, text="t", sensitivity=Privacy.WORK_PRIVATE, edited=False, now=NOW)
            await store.finish_accept(b.id, "task", "t-9", now=NOW)
            second, _ = await store.enqueue(run_of(transcript_hash=content_hash("corrected"), inputs_hash=content_hash("c|v")), force=False)
            await store.claim_next(NOW)
            newer = [item_of(second, "Alice will email the vendor about licensing", segment=0, text="Email the vendor about licensing", transcript_hash=second.transcript_hash),
                     item_of(second, update + " tomorrow", segment=0, text="changed wording", transcript_hash=second.transcript_hash)]
            assert await store.complete_run(second.id, newer, model="m", rejected={}, now=NOW) == 0  # the same two findings: nothing new
            by_id = {i.id: i for i in await store.list_items(meeting_id="m1")}
            assert by_id[a.id].text == "Email the vendor about licensing" and by_id[a.id].transcript_hash == second.transcript_hash  # undecided: refreshed
            assert by_id[b.id].text == b.text and by_id[b.id].status is ItemStatus.ACCEPTED and by_id[b.id].transcript_hash == b.transcript_hash  # decided: untouched
        finally:
            await store.close()

    asyncio.run(go())
