"""Phase 53 on real PostgreSQL (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector): migration 034 and its rollback script, the structural guarantees, the real store
under concurrency and crash recovery, deletion of derived data, and the whole flow (attach, align, review, analyse, confirm, delete) over the real stores. Synthetic data only."""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from companion_core.document_library.access import access_from_ceiling
from companion_core.meeting_multimodal.models import (
    Alignment,
    Alt,
    Certainty,
    Cite,
    Item,
    ItemKind,
    ItemStatus,
    Link,
    Review,
    ReviewDecision,
    Run,
    RunKind,
    digest,
    item_fingerprint,
)
from companion_core.meeting_multimodal.postgres_store import PostgresMultimodalStore
from companion_core.meeting_multimodal.service import MeetingMultimodalService
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.migrations.__main__ import upgrade
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.secrets import Keyring
from companion_core.tasks.postgres_store import PostgresTaskStore
from mm_fixtures import ARCH, DECK_A, SECURITY, FakeLibrary, Model, make_meeting

from shared.models.response import Privacy

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
KEYS = Keyring("one", {"one": b"\x01" * 32})
ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-034.sql"
ROLLBACK_035 = ROLLBACK.with_name("rollback-035.sql")  # the head is 035 now (speaker identity): it is undone first
ROLLBACK_036 = ROLLBACK.with_name("rollback-036.sql")  # the head is 036 now (meeting email): it is undone first
ROLLBACK_037 = ROLLBACK_036.with_name("rollback-037.sql")  # the head is 037 now (processing provenance): it is undone first
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
OWNER = access_from_ceiling("sensitive")
CHOICES = [("jetson edge node", None, "Edge Architecture"), ("certificate rotation", None, "Security Posture")]


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


TABLES = {"meeting_document_links", "meeting_multimodal_runs", "meeting_slide_alignments", "meeting_slide_reviews", "meeting_multimodal_items"}


def run_of(meeting_id="m1", kind=RunKind.ALIGNMENT, **over):
    base = {"meeting_id": meeting_id, "kind": kind, "transcript_hash": digest("t"), "doc_revisions": {"d1": "r1"}, "inputs_hash": digest("t", "r1"), "created_at": NOW}
    base.update(over)
    return Run(**base)


def alignment_of(run, key="0-2", document_id="d1", page=2, **over):
    base = {"run_id": run.id, "meeting_id": run.meeting_id, "window_key": key, "segment_ids": [0, 1, 2], "start": 0.0, "end": 26.0, "document_id": document_id, "page": page,
            "locator": f"doc:{document_id}/page:{page}" if document_id else None, "certainty": Certainty.HIGH if document_id else Certainty.UNKNOWN, "transcript_revision": "tr",
            "document_revision": "r1" if document_id else "", "sensitivity": Privacy.WORK_PRIVATE, "created_at": NOW}
    base.update(over)
    return Alignment(**base)


def item_of(run, quote, kind=ItemKind.ACTION, *, document_id=None, **over):
    evidence = [Cite(source="transcript", quote=quote, segment=0, segments=[0], start=0.0, end=8.0, speaker="Speaker 1")]
    if document_id:
        evidence.append(Cite(source="document", quote="a page quote", document_id=document_id, page=2, locator=f"doc:{document_id}/page:2", source_hash="h", revision="r1"))
    base = {"run_id": run.id, "meeting_id": run.meeting_id, "transcript_hash": run.transcript_hash, "kind": kind, "text": quote[:40], "evidence": evidence,
            "status": ItemStatus.PENDING if kind is ItemKind.ACTION else ItemStatus.NOTED, "fingerprint": item_fingerprint(kind, evidence[0]), "sensitivity": Privacy.WORK_PRIVATE, "created_at": NOW}
    base.update(over)
    return Item(**base)


# ---- migration 034 ------------------------------------------------------------------------------------------------------------------------------

def test_the_migration_creates_only_its_own_tables_with_no_foreign_keys_and_no_triggers(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("037_processing_provenance",)]
    assert {r[0] for r in sql(dsn, "SELECT tablename FROM pg_tables WHERE tablename LIKE 'meeting_%' OR tablename = 'meeting_slide_alignments'")} >= TABLES
    for table in TABLES:
        assert sql(dsn, f"SELECT count(*) FROM pg_constraint WHERE conrelid = '{table}'::regclass AND contype = 'f'") == [(0,)]  # no key into meetings, documents or tasks
        assert sql(dsn, f"SELECT count(*) FROM pg_trigger WHERE tgrelid = '{table}'::regclass AND NOT tgisinternal") == [(0,)]  # nothing is indexed for retrieval
    upgrade(dsn, KEYS)  # a repeat changes nothing


def test_structural_guarantees_one_link_one_active_run_one_estimate_per_window_and_no_item_without_evidence(dsn):
    async def go():
        store = await PostgresMultimodalStore.connect(dsn)
        try:
            link = Link(meeting_id="m1", document_id="d1", linked_by="owner")
            results = await asyncio.gather(*(store.add_link(link) for _ in range(5)))
            assert sum(1 for _, created in results if created) == 1 and len(await store.list_links("m1")) == 1  # concurrent attach: one row
            first, created = await store.enqueue(run_of(), force=False)
            assert created
            for _ in range(3):
                again, created = await store.enqueue(run_of(), force=True)  # even a forced request cannot start a second active run of the same kind
                assert not created and again.id == first.id
            other, created = await store.enqueue(run_of(kind=RunKind.ANALYSIS), force=False)
            assert created and other.id != first.id  # but the other kind is independent
        finally:
            await store.close()

    asyncio.run(go())
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, "INSERT INTO meeting_multimodal_items (id, run_id, meeting_id, transcript_hash, kind, text, evidence, status, fingerprint, prompt_version, sensitivity, created_at) "
                 "VALUES ('i','r','m','h','decision','t','[]','noted','f','v','work-private',now())")
    with pytest.raises(psycopg.errors.UniqueViolation):
        sql(dsn, "INSERT INTO meeting_slide_alignments (id, run_id, meeting_id, window_key, segment_ids, start_s, end_s, certainty, method, relation, transcript_revision, analysis_version, sensitivity, created_at) "
                 "VALUES ('a','r','m','0-1','[]',0,1,'unknown','none','supports','t','v','work-private',now()), ('b','r','m','0-1','[]',0,1,'unknown','none','supports','t','v','work-private',now())")
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, "INSERT INTO meeting_slide_alignments (id, run_id, meeting_id, window_key, segment_ids, document_id, start_s, end_s, certainty, method, relation, transcript_revision, analysis_version, sensitivity, created_at) "
                 "VALUES ('c','r','m','0-1','[]','d1',0,1,'high','semantic','supports','t','v','work-private',now())")  # a document without a page


def test_the_rollback_script_removes_only_this_phase_and_the_migration_applies_again(dsn):
    sql(dsn, "INSERT INTO tasks (id, text, status, created_at) VALUES ('t1','confirmed from a meeting and a deck','open',now())")
    sql(dsn, "INSERT INTO meetings (id, title, source_filename, content_type, audio_path, status) VALUES ('m1','x','a','b','c','complete')")
    sql(dsn, "INSERT INTO meeting_document_links (meeting_id, document_id, linked_by, created_at, updated_at) VALUES ('m1','d1','owner',now(),now())")
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK_037.read_text())
        conn.execute(ROLLBACK_036.read_text())
        conn.execute(ROLLBACK_035.read_text())
        conn.execute(ROLLBACK.read_text())  # one transaction, as the script's own instructions require
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("033_calendar_feed",)]
    assert sql(dsn, "SELECT count(*) FROM pg_tables WHERE tablename = ANY(%s)", (list(TABLES),)) == [(0,)]
    assert sql(dsn, "SELECT text FROM tasks") == [("confirmed from a meeting and a deck",)] and sql(dsn, "SELECT count(*) FROM meetings") == [(1,)]  # authoritative data stays
    upgrade(dsn, KEYS)
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("037_processing_provenance",)] and sql(dsn, "SELECT count(*) FROM meeting_document_links") == [(0,)]


# ---- the real store -----------------------------------------------------------------------------------------------------------------------------

def test_lease_takeover_replacement_of_estimates_and_reviews_that_survive_it(dsn):
    async def go():
        store = await PostgresMultimodalStore.connect(dsn)
        try:
            r, _ = await store.enqueue(run_of(), force=False)
            claimed = await store.claim_next(NOW)
            assert claimed is not None and claimed.attempts == 1 and await store.claim_next(NOW) is None
            retaken = await store.claim_next(NOW + timedelta(hours=1))  # the lease expired: another worker takes it over
            assert retaken is not None and retaken.id == r.id and retaken.attempts == 2
            assert await store.complete_alignment(r.id, [alignment_of(r, "0-2"), alignment_of(r, "3-5", document_id=None, page=None)], model="m", stats={"windows": 2}, now=NOW) == 2
            assert await store.complete_alignment(r.id, [alignment_of(r, "0-2")], model="m", stats={}, now=NOW) == 0  # a finished run completes once
            await store.set_review(Review(meeting_id="m1", window_key="0-2", decision=ReviewDecision.REPLACED, document_id="d1", page=5, transcript_revision="tr", document_revision="r1"))
            second, _ = await store.enqueue(run_of(inputs_hash="other"), force=True)
            await store.claim_next(NOW + timedelta(hours=2))
            await store.complete_alignment(second.id, [alignment_of(second, "0-2", page=3)], model="m", stats={}, now=NOW)
            rows = await store.list_alignments("m1")
            assert [(a.window_key, a.page) for a in rows] == [("0-2", 3)]  # the set was replaced: no stale rows from the earlier run
            (review,) = await store.list_reviews("m1")
            assert (review.decision, review.page) == (ReviewDecision.REPLACED, 5)  # the owner's decision is untouched by a rerun
            assert (await store.set_review(review.model_copy(update={"decision": ReviewDecision.NO_SLIDE, "document_id": None, "page": None}))).created_at == review.created_at
            assert await store.clear_review("m1", "0-2") and not await store.clear_review("m1", "0-2")
        finally:
            await store.close()

    asyncio.run(go())


def test_findings_accept_once_and_a_dismissed_one_is_not_brought_back(dsn):
    async def go():
        store = await PostgresMultimodalStore.connect(dsn)
        try:
            r, _ = await store.enqueue(run_of(kind=RunKind.ANALYSIS), force=False)
            await store.claim_next(NOW)
            action, question = item_of(r, "Priya will own the rotation by Friday"), item_of(r, "Who owns the audit logging", ItemKind.OPEN_QUESTION)
            assert await store.complete_analysis(r.id, [action, question], model="m", stats={}, now=NOW) == 2
            claims = await asyncio.gather(*(store.claim_accept(action.id, text="Do it", sensitivity=Privacy.WORK_PRIVATE, edited=False, now=NOW) for _ in range(4)))
            assert sorted(c.outcome for c in claims).count("claimed") == 1  # four simultaneous confirmations: one claim
            done = await store.finish_accept(action.id, "task", "task-1", now=NOW)
            assert done is not None and done.status is ItemStatus.ACCEPTED
            assert (await store.dismiss(question.id, now=NOW)).outcome == "done"
            r2, _ = await store.enqueue(run_of(kind=RunKind.ANALYSIS, inputs_hash="again"), force=True)
            await store.claim_next(NOW)
            added = await store.complete_analysis(r2.id, [item_of(r2, "Priya will own the rotation by Friday"), item_of(r2, "Who owns the audit logging", ItemKind.OPEN_QUESTION)], model="m", stats={}, now=NOW)
            assert added == 0 and len(await store.list_items(meeting_id="m1")) == 2
            assert (await store.item_for_record("task-1")).id == action.id
        finally:
            await store.close()

    asyncio.run(go())


def test_removing_a_document_clears_its_derived_rows_everywhere_and_one_attachment_only_for_its_meeting(dsn):
    async def go():
        store = await PostgresMultimodalStore.connect(dsn)
        try:
            for meeting in ("m1", "m2"):
                await store.add_link(Link(meeting_id=meeting, document_id="d1", linked_by="owner"))
                await store.add_link(Link(meeting_id=meeting, document_id="d2", linked_by="owner"))
                run, _ = await store.enqueue(run_of(meeting, doc_revisions={"d1": "r1", "d2": "r1"}), force=False)
                await store.claim_next(NOW)
                keep = alignment_of(run, "3-5", document_id="d2", page=1, alternatives=[Alt(document_id="d1", page=2, locator="doc:d1/page:2")])
                await store.complete_alignment(run.id, [alignment_of(run, "0-2"), keep], model="m", stats={}, now=NOW)
                await store.set_review(Review(meeting_id=meeting, window_key="0-2", decision=ReviewDecision.CONFIRMED, document_id="d1", page=2, transcript_revision="tr", document_revision="r1"))
                arun, _ = await store.enqueue(run_of(meeting, kind=RunKind.ANALYSIS, doc_revisions={"d1": "r1"}), force=False)
                await store.claim_next(NOW)
                await store.complete_analysis(arun.id, [item_of(arun, "A transcript-only finding", ItemKind.DECISION), item_of(arun, "A finding with a page", ItemKind.DISCUSSION, document_id="d1"),
                                                         item_of(arun, "Accepted action with a page", document_id="d1")], model="m", stats={}, now=NOW)
            accepted = next(i for i in await store.list_items(meeting_id="m1") if i.text.startswith("Accepted"))
            await store.claim_accept(accepted.id, text="x", sensitivity=Privacy.WORK_PRIVATE, edited=False, now=NOW)
            await store.finish_accept(accepted.id, "task", "t", now=NOW)

            await store.remove_link("m1", "d1")
            await store.drop_document("d1", meeting_id="m1")  # one attachment removed: only that meeting is affected
            assert {l.document_id for l in await store.list_links("m1")} == {"d2"} and {l.document_id for l in await store.list_links("m2")} == {"d1", "d2"}
            assert [a.window_key for a in await store.list_alignments("m1")] == ["3-5"] and (await store.list_alignments("m1"))[0].alternatives == []
            assert len(await store.list_alignments("m2")) == 2 and len(await store.list_reviews("m2")) == 1 and await store.list_reviews("m1") == []

            await store.drop_document("d1")  # the document itself is deleted: every meeting
            assert len(await store.list_alignments("m2")) == 1 and await store.list_reviews("m2") == [] and {l.document_id for l in await store.list_links("m2")} == {"d2"}
            left = await store.list_items(meeting_id="m2")
            assert {i.text for i in left} == {"A transcript-only finding"}
            kept = next(i for i in await store.list_items(meeting_id="m1") if i.status is ItemStatus.ACCEPTED)
            assert [c.source for c in kept.evidence] == ["transcript"]  # the task survives and so does its transcript evidence; the page quote does not
            assert (await store.get_run((await store.latest_run("m2", RunKind.ANALYSIS)).id)).doc_revisions == {}
            assert await store.drop_meeting("m2") > 0 and await store.list_links("m2") == [] and await store.list_items(meeting_id="m2") == []
            assert (await store.latest_run("m2", RunKind.ALIGNMENT)) is None
        finally:
            await store.close()

    asyncio.run(go())


# ---- the whole flow on real stores ---------------------------------------------------------------------------------------------------------------

def test_the_whole_flow_over_the_real_store_and_task_store(dsn):
    async def go():
        store = await PostgresMultimodalStore.connect(dsn)
        tasks, planner = await PostgresTaskStore.connect(dsn), await PostgresPlannerStore.connect(dsn)
        try:
            lib, meetings, model = FakeLibrary(), InMemoryMeetingStore(), Model(CHOICES)
            meeting = make_meeting([ARCH, SECURITY])
            meetings._meetings[meeting.id] = meeting
            doc = await lib.add(*DECK_A)
            svc = MeetingMultimodalService(store, meetings, lib, tasks, planner, provider=model.provider)
            lib.deletion_listeners.append(svc.document_deleted)

            def script(_user):
                quote = "Priya will own certificate rotation by Friday"
                index = next(i for i, s in enumerate(meeting.transcript_segments) if quote in s["text"])
                return [{"type": "action", "text": "Priya to own certificate rotation", "evidence": [{"source": "T", "segment": index, "quote": quote}], "assignee": "Priya", "stated_time": "by Friday", "ambiguities": []}]

            model.analysis = script
            await svc.link(meeting.id, doc.id, OWNER)
            await svc.enqueue_analysis(meeting.id, OWNER)
            assert await svc.process_next() and await svc.process_next()
            view = await svc.overview(meeting.id, OWNER)
            assert view["alignment"]["state"] == "succeeded" and view["analysis"]["state"] == "succeeded" and view["windows"][0]["shown"]["page"] == 2
            assert view["alignment"]["run"]["stats"]["asked"] >= 1 and view["analysis"]["run"]["stats"]["elapsed_ms"] >= 0
            assert await tasks.list_tasks() == []
            (action,) = view["analysis"]["items"]
            a = await svc.accept(action["id"], OWNER)
            b = await svc.accept(action["id"], OWNER)
            assert a["record"] == b["record"] and len(await tasks.list_tasks()) == 1
            await svc.review(meeting.id, view["windows"][0]["window_key"], OWNER, decision="no_slide")
            await lib.delete(doc.id)
            after = await svc.overview(meeting.id, OWNER)
            assert after["documents"] == [] and after["windows"] == [] and after["analysis"]["items"][0]["status"] == "accepted"
            assert sql(dsn, "SELECT count(*) FROM meeting_document_links") == [(0,)] and sql(dsn, "SELECT count(*) FROM meeting_slide_reviews") == [(1,)]  # a "no slide" decision names no document, so it stays
        finally:
            await store.close()
            await tasks.close()
            await planner.close()

    asyncio.run(go())
