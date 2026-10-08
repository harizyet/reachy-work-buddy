"""Phase 44B, without a database: how the stores are described to the knowledge layer (adapters), how the worker keeps the index in
step (idempotence, change detection, failure and lease recovery, the generation guard, reconciliation) and, most importantly, that
retrieval-time revalidation never returns what a source no longer allows, whatever stale state the index is in.

The index and outbox here are the in-memory implementations; tests/test_knowledge_postgres.py repeats the important cases on real
Postgres, where the triggers fill the outbox."""

import asyncio
import hashlib
import threading
from datetime import UTC, datetime, timedelta

import pytest
from companion_core.knowledge.index import InMemoryKnowledgeIndex
from companion_core.knowledge.outbox import MAX_ATTEMPTS, InMemoryOutbox, backoff
from companion_core.knowledge.revalidate import Candidate, revalidate
from companion_core.knowledge.sources import GENERATED_CONFIDENCE, build_adapters
from companion_core.knowledge.worker import IndexingWorker
from companion_core.meetings.models import MeetingJobStatus, MeetingOutput
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.semantic import access
from companion_core.semantic.model import AccessContext, SourceRef
from companion_core.tasks.store import InMemoryTaskStore

from shared.models.response import Privacy

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def embed(texts):
    out = []
    for text in texts:
        vector = [0.0] * 384
        for word in text.lower().split():
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        out.append([v / norm for v in vector] if norm else vector)
    return out


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class World:
    """All six stores, their adapters, an in-memory index and outbox, and a worker with a controllable clock and an embed counter."""

    def __init__(self, embedder=embed):
        self.clock = Clock()
        self.memory, self.meetings, self.planner = InMemoryMemoryStore(), InMemoryMeetingStore(), InMemoryPlannerStore()
        self.tasks, self.documents = InMemoryTaskStore(), InMemoryDocumentStore(embed_fn=embed)
        self.adapters = build_adapters(
            memory=self.memory, documents=self.documents, meetings=self.meetings, planner=self.planner, tasks=self.tasks,
            clock=self.clock,
        )
        self.index, self.outbox = InMemoryKnowledgeIndex(), InMemoryOutbox()
        self.embedded: list[str] = []

        def counting(texts):
            self.embedded.extend(texts)
            return embedder(texts)

        self.counting = counting
        self.worker = IndexingWorker(
            adapters=self.adapters, index=self.index, outbox=self.outbox, embed_fn=counting, embedding_model="test-model",
            clock=self.clock,
        )

    async def meeting(self, segments, *, sensitivity=Privacy.WORK_PRIVATE, scope=None, names=None):
        m = await self.meetings.create_meeting(
            title="Weekly sync", audio=b"x", source_filename="m.wav", content_type="audio/wav", sensitivity=sensitivity,
            project_scope=scope,
        )
        self.meetings._touch(
            m, transcript_segments=[{"start": float(i), "end": float(i + 1), "text": t} for i, (t, _) in enumerate(segments)],
            diarization_segments=[{"start": float(i), "end": float(i + 1), "speaker": s} for i, (_, s) in enumerate(segments)],
            status=MeetingJobStatus.ALIGNING,
        )
        await self.meetings.set_speaker_names(m.id, names or {"SPEAKER_00": "Priya"})
        return m.id

    async def sync(self, source_type, source_id):
        return await self.worker.sync_source(source_type, source_id)

    def ctx(self, **kw):
        base = {"principal": "o", "sensitivity_ceiling": Privacy.WORK_PRIVATE}
        return AccessContext(**{**base, **kw})


def run(coro):
    return asyncio.run(coro)


def cand(source_type, source_id, locator=None, sensitivity=Privacy.PUBLIC):
    return Candidate(SourceRef(source_type=source_type, source_id=source_id, locator=locator), sensitivity)


# ---- adapters ---------------------------------------------------------------------------------------------------

def test_each_store_is_described_with_its_classification_scope_and_provenance() -> None:
    async def go():
        w = World()
        mem = await w.memory.add_memory(content="Falcon-7B is the default", source="chat", sensitivity=Privacy.SENSITIVE,
                                        project_scope="harbor", confidence=0.8)
        doc = await w.documents.ingest_document(title="Arch", content="# Queue\nretries five\n\n# Model\nfalcon", source="s",
                                                sensitivity=Privacy.PUBLIC, project_scope="harbor")
        note = await w.planner.add_note("Actions", "Tomas benchmarks", sensitivity=Privacy.PUBLIC, project_scope="harbor")
        task = await w.tasks.add_task("Send summary", project_scope="lantern")
        rem = await w.planner.add_reminder("Weekly sync", T0 + timedelta(days=1), sensitivity=Privacy.SENSITIVE)
        mid = await w.meeting([("hello team", "SPEAKER_00"), ("retries are five", "SPEAKER_00")], scope="harbor")

        (m,) = (await w.adapters["memory"].state(mem.id)).items
        assert (m.kind, m.sensitivity, m.project_scope, m.confidence, m.local_only) == ("memory", Privacy.SENSITIVE, "harbor", 0.8, False)
        chunks = (await w.adapters["document"].state(doc[0].document_id)).items
        assert [c.ref.key for c in chunks] == [f"document:{doc[0].document_id}#0", f"document:{doc[0].document_id}#1"]
        assert chunks[0].section == "Queue" and chunks[0].title == "Arch" and chunks[0].sensitivity == Privacy.PUBLIC
        (n,) = (await w.adapters["note"].state(note.id)).items
        assert n.text == "Actions\nTomas benchmarks" and n.project_scope == "harbor"
        (t,) = (await w.adapters["task"].state(task.id)).items
        assert (t.sensitivity, t.project_scope) == (Privacy.WORK_PRIVATE, "lantern")
        (r,) = (await w.adapters["reminder"].state(rem.id)).items
        assert r.sensitivity == Privacy.SENSITIVE and "2026-10-09" in r.match_text and "2026" not in r.text
        seg = (await w.adapters["meeting"].state(mid)).items
        assert [s.ref.key for s in seg] == [f"meeting:{mid}#0", f"meeting:{mid}#1"]
        assert seg[0].local_only and seg[0].speaker == "Priya" and seg[0].match_text == "Priya: hello team"

    run(go())


def test_meeting_text_is_what_the_owner_accepted_not_the_raw_transcript() -> None:
    async def go():
        w = World()
        mid = await w.meeting([("falcon seven bee restarts", "SPEAKER_00")])
        await w.meetings.set_correction(mid, 0, "Falcon-7B restarts")
        (item,) = (await w.adapters["meeting"].state(mid)).items
        assert item.text == "Falcon-7B restarts" and "seven bee" not in item.match_text
        stored = await w.meetings.get_meeting(mid)
        assert stored.transcript_segments[0]["text"] == "falcon seven bee restarts"  # the evidence is untouched

    run(go())


def test_generated_summaries_are_marked_as_model_written_and_ranked_below_speech() -> None:
    async def go():
        w = World()
        mid = await w.meeting([("we chose five retries", "SPEAKER_00")])
        await w.meetings.set_output(mid, "summary", MeetingOutput(text="The team chose five retries.", tier="local"))
        items = {i.ref.locator: i for i in (await w.adapters["meeting"].state(mid)).items}
        assert items["summary"].authority == "model_generated" and items["summary"].confidence == GENERATED_CONFIDENCE
        assert items["0"].authority == "source" and items["0"].confidence == 1.0

    run(go())


def test_not_visible_sources_produce_no_items_and_say_why() -> None:
    async def go():
        w = World()
        gone = await w.memory.add_memory(content="x", source="s")
        await w.memory.forget(gone.id)
        old = await w.memory.add_memory(content="y", source="s", expires_at=T0 - timedelta(days=1))
        assert (await w.adapters["memory"].state(gone.id)).status == "forgotten"
        assert (await w.adapters["memory"].state(old.id)).status == "expired"
        assert (await w.adapters["memory"].state("nope")).status == "missing"
        mid = await w.meeting([("hi", "SPEAKER_00")])
        await w.meetings.cancel_meeting(mid)
        assert (await w.adapters["meeting"].state(mid)).status == "hidden"
        fresh = await w.meetings.create_meeting(title="x", audio=b"x", source_filename="a.wav", content_type="audio/wav")
        assert (await w.adapters["meeting"].state(fresh.id)).status == "hidden"  # nothing transcribed yet
        for adapter, sid in ((w.adapters["note"], "n"), (w.adapters["task"], "t"), (w.adapters["reminder"], "r"), (w.adapters["document"], "d")):
            assert (await adapter.state(sid)).status == "missing"

    run(go())


def test_versions_are_stable_and_change_with_anything_that_matters() -> None:
    async def go():
        w = World()
        note = await w.planner.add_note("A", "body", sensitivity=Privacy.WORK_PRIVATE)
        first = (await w.adapters["note"].state(note.id)).items[0].version()
        assert first == (await w.adapters["note"].state(note.id)).items[0].version()
        await w.planner.update_note(note.id, "A", "body changed")
        second = (await w.adapters["note"].state(note.id)).items[0].version()
        assert second != first
        w.planner._notes[note.id].sensitivity = Privacy.SENSITIVE
        third = (await w.adapters["note"].state(note.id)).items[0].version()
        assert third not in (first, second)
        w.planner._notes[note.id].project_scope = "alpha"
        assert (await w.adapters["note"].state(note.id)).items[0].version() != third

    run(go())


# ---- worker -----------------------------------------------------------------------------------------------------

def test_sync_indexes_new_text_once_and_a_repeat_changes_nothing() -> None:
    async def go():
        w = World()
        n = await w.planner.add_note("Actions", "Tomas benchmarks falcon")
        first = await w.sync("note", n.id)
        assert (first.upserted, first.deleted) == (1, 0) and await w.index.count() == 1
        row = await w.index.get(f"note:{n.id}")
        assert row.sensitivity == Privacy.WORK_PRIVATE and row.embedding_model == "test-model" and "falcon" in row.match_text
        embedded_before = len(w.embedded)
        again = await w.sync("note", n.id)
        assert (again.upserted, again.deleted, again.unchanged) == (0, 0, 1) and len(w.embedded) == embedded_before
        assert await w.index.count() == 1

    run(go())


def test_only_changed_parts_are_embedded_again() -> None:
    async def go():
        w = World()
        mid = await w.meeting([(f"line {i} about topic{i}", "SPEAKER_00") for i in range(6)])
        await w.sync("meeting", mid)
        assert len(w.embedded) == 6
        await w.meetings.set_correction(mid, 3, "line 3 about corrected")
        result = await w.sync("meeting", mid)
        assert (result.upserted, result.unchanged) == (1, 5) and len(w.embedded) == 7 and "corrected" in w.embedded[-1]
        await w.meetings.set_speaker_names(mid, {"SPEAKER_00": "Dana"})  # every match text carries the speaker
        assert (await w.sync("meeting", mid)).upserted == 6

    run(go())


def test_a_part_that_disappears_is_removed_and_a_hidden_source_is_removed_whole() -> None:
    async def go():
        w = World()
        mid = await w.meeting([("a one", "SPEAKER_00"), ("b two", "SPEAKER_00"), ("c three", "SPEAKER_00")])
        await w.sync("meeting", mid)
        assert await w.index.count() == 3
        m = await w.meetings.get_meeting(mid)
        w.meetings._touch(m, transcript_segments=m.transcript_segments[:2])
        result = await w.sync("meeting", mid)
        assert result.deleted == 1 and await w.index.count() == 2 and await w.index.get(f"meeting:{mid}#2") is None
        await w.meetings.cancel_meeting(mid)
        assert (await w.sync("meeting", mid)).deleted == 2 and await w.index.count() == 0

    run(go())


def test_a_forgotten_deleted_or_expired_record_leaves_the_index_when_synced() -> None:
    async def go():
        w = World()
        a = await w.memory.add_memory(content="alpha fact", source="s")
        b = await w.memory.add_memory(content="beta fact", source="s", expires_at=T0 + timedelta(hours=1))
        t = await w.tasks.add_task("gamma task")
        for st, sid in (("memory", a.id), ("memory", b.id), ("task", t.id)):
            await w.sync(st, sid)
        assert await w.index.count() == 3
        await w.memory.forget(a.id)
        await w.tasks.delete_task(t.id)
        w.clock.now = T0 + timedelta(hours=2)  # beta expires with the passage of time alone
        for st, sid in (("memory", a.id), ("memory", b.id), ("task", t.id)):
            await w.sync(st, sid)
        assert await w.index.count() == 0
        await w.memory.restore(a.id)
        await w.sync("memory", a.id)
        assert await w.index.get(f"memory:{a.id}") is not None  # undo works: restoring brings it back

    run(go())


def test_the_embedder_runs_off_the_event_loop_thread_and_in_small_batches() -> None:
    async def go():
        seen = []
        sizes = []

        def spy(texts):
            seen.append(threading.get_ident())
            sizes.append(len(texts))
            return embed(texts)

        w = World(embedder=spy)
        mid = await w.meeting([(f"segment {i}", "SPEAKER_00") for i in range(40)])
        await w.sync("meeting", mid)
        assert set(seen) != {threading.get_ident()}
        assert max(sizes) <= 16 and sum(sizes) == 40

    run(go())


def test_changing_the_embedding_model_reembeds_everything_once() -> None:
    async def go():
        w = World()
        n = await w.planner.add_note("A", "b")
        await w.sync("note", n.id)
        w.worker.embedding_model = "better-model"
        assert (await w.sync("note", n.id)).upserted == 1
        assert (await w.index.get(f"note:{n.id}")).embedding_model == "better-model"
        assert (await w.sync("note", n.id)).upserted == 0

    run(go())


def test_run_once_works_the_outbox_and_survives_one_bad_source() -> None:
    async def go():
        w = World()
        ok = await w.planner.add_note("fine", "body")
        await w.outbox.enqueue("note", ok.id, T0)
        await w.outbox.enqueue("note", "vanished", T0)  # a source that was deleted before the worker got to it
        await w.outbox.enqueue("bogus", "x", T0)  # an unknown type fails, alone
        result = await w.worker.run_once()
        assert (result.processed, result.failed) == (3, 1) and await w.index.count() == 1
        status = await w.outbox.status(T0)
        assert status.pending == 1  # only the failing one is left, waiting to retry

    run(go())


def test_failures_back_off_and_a_row_that_keeps_failing_is_set_aside_until_a_change_revives_it() -> None:
    async def go():
        w = World()
        await w.outbox.enqueue("bogus", "x", T0)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            w.clock.now = T0 + timedelta(days=attempt)
            result = await w.worker.run_once()
            assert result.failed == 1, attempt
        status = await w.outbox.status(w.clock.now)
        assert (status.pending, status.failed) == (0, 1)
        w.clock.now += timedelta(days=30)
        assert (await w.worker.run_once()).processed == 0  # poisoned rows are not retried forever
        await w.outbox.enqueue("bogus", "x", w.clock.now)  # a new change revives it
        assert (await w.worker.run_once()).processed == 1
        assert backoff(1) == timedelta(minutes=1) and backoff(2) == timedelta(minutes=2) and backoff(20) == timedelta(hours=1)

    run(go())


def test_a_retry_waits_for_its_backoff() -> None:
    async def go():
        w = World()
        await w.outbox.enqueue("bogus", "x", T0)
        assert (await w.worker.run_once()).failed == 1
        w.clock.now = T0 + timedelta(seconds=30)
        assert (await w.worker.run_once()).processed == 0  # still inside the first minute
        w.clock.now = T0 + timedelta(seconds=61)
        assert (await w.worker.run_once()).processed == 1

    run(go())


def test_a_crashed_workers_claim_is_retried_after_its_lease_expires_and_nothing_is_lost() -> None:
    async def go():
        w = World()
        n = await w.planner.add_note("A", "b")
        await w.outbox.enqueue("note", n.id, T0)
        crashed = await w.outbox.claim(T0, lease_seconds=300, limit=10)  # a worker takes it, then dies
        assert len(crashed) == 1 and await w.index.count() == 0
        w.clock.now = T0 + timedelta(seconds=100)
        assert (await w.worker.run_once()).processed == 0  # the lease is still held
        w.clock.now = T0 + timedelta(seconds=301)
        assert (await w.worker.run_once()).processed == 1 and await w.index.count() == 1

    run(go())


def test_a_change_that_lands_while_a_source_is_being_synced_is_not_swallowed() -> None:
    async def go():
        w = World()
        n = await w.planner.add_note("A", "first body")
        await w.outbox.enqueue("note", n.id, T0)
        (claimed,) = await w.outbox.claim(T0, lease_seconds=300, limit=1)
        await w.worker.sync_source("note", n.id)
        await w.planner.update_note(n.id, "A", "second body")  # the source changes mid-sync...
        await w.outbox.enqueue("note", n.id, T0)  # ...and its trigger fires
        assert await w.outbox.complete(claimed, T0) is False  # so this completion must not delete the new event
        assert (await w.outbox.status(T0)).pending == 1
        result = await w.worker.drain()
        assert result.processed >= 1 and "second" in (await w.index.get(f"note:{n.id}")).match_text

    run(go())


def test_duplicate_events_for_one_source_collapse_to_a_single_sync() -> None:
    async def go():
        w = World()
        n = await w.planner.add_note("A", "b")
        for _ in range(5):
            await w.outbox.enqueue("note", n.id, T0)
        assert (await w.outbox.status(T0)).pending == 1
        assert (await w.worker.drain()).processed == 1

    run(go())


def test_the_worker_never_modifies_a_store() -> None:
    async def go():
        w = World()
        m = await w.memory.add_memory(content="one", source="s")
        n = await w.planner.add_note("A", "b")
        t = await w.tasks.add_task("c")
        before = (m.model_dump(), n.model_dump(), t.model_dump())
        for st, sid in (("memory", m.id), ("note", n.id), ("task", t.id)):
            await w.sync(st, sid)
        await w.worker.reconcile()
        after = ((await w.memory.get_any(m.id)).model_dump(), (await w.planner.get_note(n.id)).model_dump(), (await w.tasks.get_task(t.id)).model_dump())
        assert after == before

    run(go())


# ---- reconciliation ---------------------------------------------------------------------------------------------

def test_reconcile_repairs_a_missing_stale_orphaned_and_expired_index() -> None:
    async def go():
        w = World()
        a = await w.planner.add_note("A", "alpha")
        b = await w.planner.add_note("B", "beta")
        c = await w.memory.add_memory(content="gamma", source="s", expires_at=T0 + timedelta(hours=1))
        for st, sid in (("note", a.id), ("note", b.id), ("memory", c.id)):
            await w.sync(st, sid)
        # damage: a row lost, a row left stale (the source moved on), an orphan for a source that is gone, time passes
        await w.index.delete_keys([f"note:{a.id}"])
        await w.planner.update_note(b.id, "B", "beta changed")
        await w.index.upsert([await _row_for(w, "note", "ghost")], [embed(["x"])[0]])
        w.clock.now = T0 + timedelta(hours=2)
        report = await w.worker.reconcile()
        assert report.orphans_deleted == 1 and report.enqueued == 3  # a (missing), b (stale), c (expired)
        await w.worker.drain()
        assert await w.index.get(f"note:{a.id}") is not None
        assert "changed" in (await w.index.get(f"note:{b.id}")).match_text
        assert await w.index.get(f"memory:{c.id}") is None and await w.index.get("note:ghost") is None
        clean = await w.worker.reconcile()
        assert (clean.enqueued, clean.orphans_deleted) == (0, 0)

    run(go())


async def _row_for(w, source_type, source_id):
    from companion_core.knowledge.index import IndexRow
    from companion_core.knowledge.sources import Indexable

    item = Indexable(ref=SourceRef(source_type=source_type, source_id=source_id), kind="note", text="ghost", match_text="ghost",
                     sensitivity=Privacy.PUBLIC, local_only=False, project_scope=None)
    return IndexRow.from_indexable(item, embedding_model="test-model", now=T0)


def test_reconcile_after_a_restore_rebuilds_a_whole_empty_index() -> None:
    async def go():
        w = World()
        await w.planner.add_note("A", "alpha")
        await w.tasks.add_task("do it")
        await w.memory.add_memory(content="fact", source="s")
        await w.meeting([("hello", "SPEAKER_00")])
        await w.documents.ingest_document(title="D", content="# S\ntext here", source="s")
        report = await w.worker.reconcile()
        assert report.enqueued == 5
        await w.worker.drain()
        assert await w.index.count() == 5

    run(go())


# ---- revalidation: the control that stops a stale index from leaking --------------------------------------------

async def indexed_world():
    w = World()
    mem = await w.memory.add_memory(content="Falcon-7B is current", source="s", sensitivity=Privacy.WORK_PRIVATE, project_scope="harbor")
    note = await w.planner.add_note("Actions", "Tomas benchmarks", sensitivity=Privacy.WORK_PRIVATE, project_scope="harbor")
    task = await w.tasks.add_task("Send summary", project_scope="harbor")
    (chunk, *_) = await w.documents.ingest_document(title="Arch", content="# Queue\nretries five", source="s", project_scope="harbor")
    mid = await w.meeting([("retries are five", "SPEAKER_00"), ("agreed", "SPEAKER_00")], scope="harbor")
    for st, sid in (("memory", mem.id), ("note", note.id), ("task", task.id), ("document", chunk.document_id), ("meeting", mid)):
        await w.sync(st, sid)
    candidates = [
        cand("memory", mem.id), cand("note", note.id), cand("task", task.id),
        cand("document", chunk.document_id, "0"), cand("meeting", mid, "0"),
    ]
    return w, candidates, {"mem": mem.id, "note": note.id, "task": task.id, "doc": chunk.document_id, "meeting": mid}


def test_current_visible_sources_are_returned_with_text_and_provenance_read_from_the_source() -> None:
    async def go():
        w, candidates, _ = await indexed_world()
        bundle = await revalidate(candidates, w.ctx(), w.adapters, now=T0)
        assert [i.ref.source_type for i in bundle.items] == ["memory", "note", "task", "document", "meeting"] and bundle.dropped == {}
        meeting = bundle.items[-1]
        assert meeting.text == "retries are five" and meeting.provenance.speaker == "Priya" and meeting.local_only
        assert bundle.local_only is True and bundle.max_sensitivity == Privacy.WORK_PRIVATE and bundle.token_estimate > 0
        assert bundle.items[3].provenance.section == "Queue" and bundle.items[3].provenance.title == "Arch"

    run(go())


@pytest.mark.parametrize("change", ["forget", "delete_note", "delete_task", "cancel_meeting", "expire", "remove_part"])
def test_a_stale_index_cannot_return_what_the_source_no_longer_allows(change) -> None:
    """The index still holds every row (the worker is behind). The source has moved on. Nothing affected may come back."""

    async def go():
        w, candidates, ids = await indexed_world()
        gone_type = {
            "forget": "memory", "delete_note": "note", "delete_task": "task", "cancel_meeting": "meeting", "expire": "memory",
            "remove_part": "meeting",
        }[change]
        if change == "forget":
            await w.memory.forget(ids["mem"])
        elif change == "delete_note":
            await w.planner.delete_note(ids["note"])
        elif change == "delete_task":
            await w.tasks.delete_task(ids["task"])
        elif change == "cancel_meeting":
            await w.meetings.cancel_meeting(ids["meeting"])
        elif change == "expire":
            w.memory._records[ids["mem"]].expires_at = T0 - timedelta(seconds=1)
        else:
            m = await w.meetings.get_meeting(ids["meeting"])
            w.meetings._touch(m, transcript_segments=[])  # no transcript left, so no part of it can exist
        assert await w.index.count() == 6  # the index was not touched: it is stale
        bundle = await revalidate(candidates, w.ctx(), w.adapters, now=T0)
        assert gone_type not in [i.ref.source_type for i in bundle.items]
        assert sum(bundle.dropped.values()) == 1 and len(bundle.items) == 4

    run(go())


def test_drop_reasons_say_why() -> None:
    async def go():
        w, candidates, ids = await indexed_world()
        await w.memory.forget(ids["mem"])
        await w.planner.delete_note(ids["note"])
        await w.meetings.cancel_meeting(ids["meeting"])
        bundle = await revalidate(candidates, w.ctx(), w.adapters, now=T0)
        assert bundle.dropped == {"forgotten": 1, "missing": 1, "deleted": 1}

    run(go())


def test_the_text_returned_is_the_sources_current_text_never_the_indexed_copy() -> None:
    async def go():
        w, candidates, ids = await indexed_world()
        await w.planner.update_note(ids["note"], "Actions", "Dana now benchmarks")  # the index still says Tomas
        assert "Tomas" in (await w.index.get(f"note:{ids['note']}")).match_text
        bundle = await revalidate(candidates, w.ctx(), w.adapters, now=T0)
        note = next(i for i in bundle.items if i.ref.source_type == "note")
        assert "Dana" in note.text and "Tomas" not in note.text

    run(go())


def test_a_reclassification_the_index_has_not_seen_still_applies_and_a_lower_index_label_never_wins() -> None:
    async def go():
        w, candidates, ids = await indexed_world()
        w.planner._notes[ids["note"]].sensitivity = Privacy.SENSITIVE  # raised in the source after indexing
        bundle = await revalidate(candidates, w.ctx(), w.adapters, now=T0)
        assert bundle.dropped == {"over_ceiling": 1}
        wide = await revalidate(candidates, w.ctx(sensitivity_ceiling=Privacy.SENSITIVE), w.adapters, now=T0)
        assert next(i for i in wide.items if i.ref.source_type == "note").sensitivity == Privacy.SENSITIVE
        # the other direction: the source was lowered but the index copy still says sensitive: the stricter label is kept
        w.planner._notes[ids["note"]].sensitivity = Privacy.PUBLIC
        marked = [cand("note", ids["note"], sensitivity=Privacy.SENSITIVE)]
        strict = await revalidate(marked, w.ctx(), w.adapters, now=T0)
        assert strict.dropped == {"over_ceiling": 1} and strict.items == []

    run(go())


def test_scope_destination_and_ceiling_are_enforced_on_what_survives() -> None:
    async def go():
        w, candidates, _ = await indexed_world()
        other = await revalidate(candidates, w.ctx(project_scopes=frozenset({"lantern"})), w.adapters, now=T0)
        assert other.items == [] and other.dropped == {"out_of_scope": 5}
        cloud = await revalidate(candidates, w.ctx(destinations=frozenset({"local", "cloud"})), w.adapters, now=T0)
        assert [i.ref.source_type for i in cloud.items] == ["memory", "note", "task", "document"] and cloud.dropped == {"destination": 1}
        assert cloud.local_only is False
        shared = await revalidate(candidates, access.access_for_owner("o", channel_private=False), w.adapters, now=T0)
        assert shared.items == [] and shared.dropped == {"over_ceiling": 5}

    run(go())


def test_historical_facts_need_the_historical_mode() -> None:
    async def go():
        w = World()
        m = await w.memory.add_memory(content="freeze until the 3rd", source="s", expires_at=T0 + timedelta(minutes=5))
        await w.sync("memory", m.id)
        later = T0 + timedelta(hours=1)
        w.clock.now = later
        # expired memories are not visible at all, in either mode
        both = [await revalidate([cand("memory", m.id)], w.ctx(), w.adapters, temporal=t, now=later) for t in ("current", "include_historical")]
        assert all(b.items == [] and b.dropped == {"expired": 1} for b in both)
        # a document chunk can carry validity in its own right; that is what temporal mode filters
        d = (await w.documents.ingest_document(title="D", content="# S\ntext", source="s"))[0]
        await w.sync("document", d.document_id)
        adapter = w.adapters["document"]
        original = adapter.state

        async def with_validity(source_id):
            state = await original(source_id)
            for k, item in enumerate(state.items):
                from dataclasses import replace

                state.items[k] = replace(item, valid_until=T0 - timedelta(days=1))
            return state

        adapter.state = with_validity
        c = [cand("document", d.document_id, "0")]
        assert (await revalidate(c, w.ctx(), w.adapters, now=T0)).dropped == {"historical": 1}
        assert len((await revalidate(c, w.ctx(), w.adapters, temporal="include_historical", now=T0)).items) == 1

    run(go())


def test_unknown_parts_unknown_types_and_repeats_are_handled() -> None:
    async def go():
        w, candidates, ids = await indexed_world()
        extra = [cand("document", ids["doc"], "9"), cand("memory", "no-such"), cand("meeting", ids["meeting"], "99"), candidates[0], candidates[0]]
        bundle = await revalidate(extra, w.ctx(), w.adapters, now=T0)
        assert len(bundle.items) == 1 and bundle.dropped == {"missing": 3}  # the repeat is ignored, not counted
        assert (await revalidate([cand("note", "x")], w.ctx(), {}, now=T0)).dropped == {"missing": 1}

    run(go())


def test_each_source_is_read_once_however_many_of_its_parts_are_candidates() -> None:
    async def go():
        w, _, ids = await indexed_world()
        calls = []
        original = w.adapters["meeting"].state

        async def counting(source_id):
            calls.append(source_id)
            return await original(source_id)

        w.adapters["meeting"].state = counting
        bundle = await revalidate([cand("meeting", ids["meeting"], "0"), cand("meeting", ids["meeting"], "1")], w.ctx(), w.adapters, now=T0)
        assert len(bundle.items) == 2 and len(calls) == 1

    run(go())


# ---- switching it on --------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("value", "expected"), [("", False), ("false", False), ("0", False), ("no", False), ("true", True), ("1", True), ("YES", True), ("on", True)])
def test_indexing_is_off_unless_the_flag_says_so(monkeypatch, value, expected) -> None:
    from companion_core.knowledge.runtime import indexing_enabled

    monkeypatch.setenv("KNOWLEDGE_INDEXING_ENABLED", value)
    assert indexing_enabled() is expected
    monkeypatch.delenv("KNOWLEDGE_INDEXING_ENABLED")
    assert indexing_enabled() is False


def test_an_app_with_injected_in_memory_stores_never_starts_the_indexer_even_when_the_flag_is_on(monkeypatch) -> None:
    from companion_core.app import create_app
    from companion_core.calendar.store import InMemoryCalendarStore
    from companion_core.consent.store import InMemoryConfirmationStore
    from companion_core.email.store import InMemoryEmailStore
    from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
    from companion_core.persona.store import InMemoryPersonaStore
    from companion_core.websearch.store import InMemorySearchSettingsStore
    from fastapi.testclient import TestClient

    monkeypatch.setenv("KNOWLEDGE_INDEXING_ENABLED", "true")
    app = create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False,
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_the_background_loop_reconciles_at_start_works_the_outbox_and_stops_on_cancel() -> None:
    async def go():
        w = World()
        n = await w.planner.add_note("Loop", "found by the startup reconcile, not by an event")
        task = asyncio.create_task(w.worker.loop(interval=0.01, reconcile_every=3600))
        for _ in range(200):
            if await w.index.count():
                break
            await asyncio.sleep(0.01)
        assert await w.index.get(f"note:{n.id}") is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)

    run(go())


def test_a_failure_never_copies_indexed_content_into_the_outbox_or_the_logs(caplog) -> None:
    """Database and library errors quote the data involved. What is stored and logged about a failure is its class and location only."""

    async def go():
        w = World()
        n = await w.planner.add_note("Private", "the launch code is 4-8-15-16-23-42")
        original = w.adapters["note"].state

        async def failing(source_id):
            await original(source_id)
            raise ValueError("could not index: the launch code is 4-8-15-16-23-42")

        w.adapters["note"].state = failing
        await w.outbox.enqueue("note", n.id, T0)
        with caplog.at_level("DEBUG"):
            assert (await w.worker.run_once()).failed == 1
        entry = next(iter(w.outbox._entries.values()))
        assert entry.last_error.startswith("ValueError at test_knowledge_index.py:")
        assert "launch code" not in entry.last_error and "4-8-15" not in entry.last_error
        assert "launch code" not in caplog.text and "4-8-15" not in caplog.text and "ValueError" in caplog.text

    run(go())
