"""Phase 49 on real PostgreSQL (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector): migration 029 and its rollback script, the structural guarantees, the real
store under concurrency and crash recovery, and the whole flow (enqueue, process with a scripted model, accept, links, task inquiry) over the real stores. Synthetic data only."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from companion_core.meetings.models import Meeting, MeetingJobStatus
from companion_core.migrations.__main__ import upgrade
from companion_core.notepad_processing import inquiry
from companion_core.notepad_processing.models import (
    Job,
    Kind,
    MeetingLink,
    content_hash,
    record_id_for,
)
from companion_core.notepad_processing.postgres_store import PostgresNotepadStore
from companion_core.notepad_processing.service import NotepadError, NotepadService
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.secrets import Keyring
from companion_core.semantic.access import access_for_owner
from companion_core.tasks.postgres_store import PostgresTaskStore

from shared.models.response import Privacy

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
KEYS = Keyring("one", {"one": b"\x01" * 32})
ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-029.sql"
ROLLBACK_030 = ROLLBACK.with_name("rollback-030.sql")  # the head is 030 now (note tags): the runbook undoes it first
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
LINE_A = "Renew the lab safety certificate before it lapses."
LINE_B = "Order two replacement servo cables."
BODY = f"{LINE_A}\n{LINE_B}\nThe lab wifi password rotates monthly."


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


def job(note_id="n1", body=BODY, **over):
    base = {"note_id": note_id, "note_title": "Tasks for next week", "snapshot_text": body, "snapshot_hash": content_hash(body), "inputs_hash": content_hash(body),
            "note_updated_at": NOW, "timezone": "UTC", "sensitivity": Privacy.WORK_PRIVATE, "created_at": NOW}
    base.update(over)
    return Job(**base)


# ---- migration 029 ----------------------------------------------------------------------------------------------------------------------------

def test_the_migration_creates_only_processing_bookkeeping_with_structural_guarantees(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("030_note_tags",)]
    assert {r[0] for r in sql(dsn, "SELECT tablename FROM pg_tables WHERE tablename LIKE 'notepad_%' OR tablename = 'note_meeting_links'")} == {
        "notepad_jobs", "notepad_proposals", "notepad_proposal_notes", "notepad_provenance", "note_meeting_links"}
    for table in ("notepad_jobs", "notepad_proposals", "notepad_proposal_notes", "notepad_provenance", "note_meeting_links"):
        assert sql(dsn, f"SELECT count(*) FROM pg_trigger WHERE tgrelid = '{table}'::regclass AND NOT tgisinternal") == [(0,)]  # nothing reaches the knowledge outbox
        assert sql(dsn, f"SELECT count(*) FROM pg_constraint WHERE conrelid = '{table}'::regclass AND contype = 'f'") == [(0,)]  # no key into notes, tasks, reminders or meetings
    upgrade(dsn, KEYS)  # a repeat changes nothing


def test_one_active_job_per_note_and_one_proposal_per_source_sentence_in_the_database_itself(dsn):
    async def go():
        store = await PostgresNotepadStore.connect(dsn)
        try:
            first, created = await store.enqueue(job(), force=False)
            assert created
            for _ in range(3):
                again, created = await store.enqueue(job(), force=True)  # even a forced request cannot start a second active job
                assert not created and again.id == first.id
        finally:
            await store.close()

    asyncio.run(go())
    with pytest.raises(psycopg.errors.UniqueViolation):
        sql(dsn, "INSERT INTO notepad_jobs (id, note_id, note_title, snapshot_text, snapshot_hash, note_updated_at, timezone, sensitivity, status, inputs_hash, created_at) "
                 "VALUES ('x','n1','t','b','h',now(),'UTC','work-private','queued','h',now())")
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, "INSERT INTO notepad_proposals (id, job_id, note_id, snapshot_hash, kind, text, evidence, span_start, span_end, evidence_from, status, fingerprint, prompt_version, sensitivity, created_at) "
                 "VALUES ('p','j','n','h','task','t','', 0, 0, 'note', 'pending', 'f', 'v', 'work-private', now())")  # no evidence span, no proposal
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, "INSERT INTO note_meeting_links (id, note_id, meeting_id, source, state, created_at, updated_at) VALUES ('l','n','m','explicit','suggested',now(),now())")


def test_the_rollback_script_removes_only_bookkeeping_and_the_migration_applies_again(dsn):
    sql(dsn, "INSERT INTO notes (id, title, body, created_at, updated_at) VALUES ('n1','t','b',now(),now())")
    sql(dsn, "INSERT INTO tasks (id, text, status, created_at) VALUES ('t1','accepted from a proposal','open',now())")
    sql(dsn, "INSERT INTO notepad_provenance VALUES ('task','t1','n1','p1','h',now())")
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK_030.read_text())
        conn.execute(ROLLBACK.read_text())  # one transaction, as the script's own instructions require
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("028_memory_candidates",)]
    assert sql(dsn, "SELECT count(*) FROM pg_tables WHERE tablename LIKE 'notepad_%' OR tablename = 'note_meeting_links'") == [(0,)]
    assert sql(dsn, "SELECT count(*) FROM notes") == [(1,)] and sql(dsn, "SELECT text FROM tasks") == [("accepted from a proposal",)]  # authoritative data stays
    upgrade(dsn, KEYS)
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("030_note_tags",)]
    assert sql(dsn, "SELECT count(*) FROM notepad_provenance") == [(0,)]


def test_the_migration_is_safe_over_leftovers_of_an_earlier_copy(dsn):
    sql(dsn, "UPDATE alembic_version SET version_num = '028_memory_candidates'")  # a restore that kept the tables
    sql(dsn, "INSERT INTO notepad_provenance VALUES ('task','stale','n','p','h',now())")
    upgrade(dsn, KEYS)
    assert sql(dsn, "SELECT count(*) FROM notepad_provenance") == [(0,)]


# ---- the real store ----------------------------------------------------------------------------------------------------------------------------

def test_dedupe_lease_takeover_and_atomic_completion_on_the_real_store(dsn):
    from companion_core.notepad_processing.models import (
        Proposal,
        ProposalStatus,
        fingerprint,
    )

    def proposal(j, evidence, kind=Kind.TASK):
        return Proposal(job_id=j.id, note_id=j.note_id, snapshot_hash=j.snapshot_hash, kind=kind, text=evidence[:20], evidence=evidence, span_start=0, span_end=len(evidence),
                        fingerprint=fingerprint(evidence), sensitivity=Privacy.WORK_PRIVATE, status=ProposalStatus.PENDING)

    async def go():
        store = await PostgresNotepadStore.connect(dsn)
        try:
            j, _ = await store.enqueue(job(), force=False)
            claimed = await store.claim_next(NOW)
            assert claimed.id == j.id and claimed.attempts == 1
            assert await store.claim_next(NOW + timedelta(seconds=5)) is None  # leased
            again = await store.claim_next(NOW + timedelta(seconds=1000))  # the runner died: lease expired
            assert again.id == j.id and again.attempts == 2
            ps = [proposal(j, LINE_A), proposal(j, LINE_B), proposal(j, LINE_A)]  # a duplicate sentence in one batch
            assert await store.complete_job(j.id, ps, model="m", now=NOW) == 2
            assert await store.complete_job(j.id, ps, model="m", now=NOW) == 0  # a second completion adds nothing
            same, created = await store.enqueue(job(), force=False)  # unchanged inputs: answered by the finished job
            assert not created and same.id == j.id
            second, created = await store.enqueue(job(), force=True)
            assert created
            await store.claim_next(NOW)
            assert await store.complete_job(second.id, [proposal(second, LINE_A), proposal(second, LINE_B)], model="m", now=NOW) == 0  # nothing resurfaces
            await store.dismiss((await store.list_proposals())[0].id, now=NOW)
            third, _ = await store.enqueue(job(), force=True)
            await store.claim_next(NOW)
            assert await store.complete_job(third.id, [proposal(third, LINE_A)], model="m", now=NOW) == 0  # not even a dismissed one
        finally:
            await store.close()

    asyncio.run(go())
    assert sql(dsn, "SELECT count(*) FROM notepad_proposals") == [(2,)]


def test_a_link_pair_is_unique_and_a_decision_is_kept(dsn):
    async def go():
        store = await PostgresNotepadStore.connect(dsn)
        try:
            link = MeetingLink(note_id="n1", meeting_id="m1", source="temporal", state="suggested", overlap_seconds=120, title_match=True, created_at=NOW, updated_at=NOW)
            await asyncio.gather(*[store.suggest_link(link.model_copy(update={"id": str(uuid4())})) for _ in range(8)])
            await asyncio.gather(*[store.set_link("n1", "m1", state="confirmed", now=NOW) for _ in range(8)])
            (row,) = await store.list_links(note_id="n1")
            assert row.state == "confirmed" and row.source == "temporal" and row.decided_at == NOW and row.overlap_seconds == 120
            await store.set_link("n1", "m1", state="rejected", now=NOW)
            again = await store.suggest_link(link.model_copy(update={"id": str(uuid4())}))
            assert again.state == "rejected"  # a rejected pair is never re-suggested
            fresh = await store.set_link("n1", "m2", state="confirmed", now=NOW)
            assert fresh.source == "explicit"
            assert await store.drop_links(meeting_id="m2") == 1
        finally:
            await store.close()

    asyncio.run(go())
    assert sql(dsn, "SELECT count(*) FROM note_meeting_links") == [(1,)]


# ---- the whole flow over the real stores -------------------------------------------------------------------------------------------------------

def test_the_whole_flow_over_real_stores_is_exactly_once_under_concurrency_and_answers_the_inquiry(dsn):
    items = [
        {"type": "task", "text": "Renew the lab safety certificate", "evidence": [LINE_A], "stated_time": None, "about_owner": True, "ambiguities": []},
        {"type": "task", "text": "Order two replacement servo cables", "evidence": [LINE_B], "stated_time": None, "about_owner": True, "ambiguities": []},
        {"type": "task", "text": "Prepare the financial report", "evidence": ["Prepare the financial report"], "stated_time": None, "about_owner": True, "ambiguities": []},
    ]

    async def provider():
        async def ask(messages, max_tokens):
            return json.dumps({"items": items})

        return ask, "scripted-7b"

    async def go():
        notes, tasks, store = await PostgresPlannerStore.connect(dsn), await PostgresTaskStore.connect(dsn), await PostgresNotepadStore.connect(dsn)
        try:
            async def zone():
                return "UTC"

            svc = NotepadService(store, notes, tasks, zone, provider=provider, clock=lambda: NOW)
            note = await notes.add_note("Tasks for next week", BODY)
            await asyncio.gather(*[svc.enqueue(note.id) for _ in range(6)])  # a storm of double clicks
            assert sql(dsn, "SELECT count(*) FROM notepad_jobs") == [(1,)]
            assert await svc.process_next() and not await svc.process_next()
            status = await svc.status(note.id)
            assert status["state"] == "review_required" and len(status["proposals"]) == 2  # the unsupported third item never existed
            assert await tasks.list_tasks() == []
            pid = status["proposals"][0]["id"]
            outcomes = await asyncio.gather(*[svc.accept(pid) for _ in range(12)], return_exceptions=True)
            assert any(isinstance(o, dict) for o in outcomes) and all(isinstance(o, dict) or (isinstance(o, NotepadError) and o.status == 409) for o in outcomes)
            await svc.accept(pid)
            assert [t.id for t in await tasks.list_tasks()] == [record_id_for(pid)]
            assert sql(dsn, "SELECT count(*) FROM notepad_provenance") == [(1,)]
            assert sql(dsn, "SELECT count(*) FROM action_receipts WHERE action_type = 'task.created'") == [(1,)]
            # a crash between the record and the close: the record exists, the proposal is stuck in accepting
            other = status["proposals"][1]["id"]
            await store.claim_accept(other, kind=Kind.TASK, text="Order two replacement servo cables", due_at=None, sensitivity=Privacy.WORK_PRIVATE, edited=False, now=NOW)
            await tasks.add_task("Order two replacement servo cables", record_id=record_id_for(other))
            svc.clock = lambda: NOW + timedelta(minutes=10)
            assert await svc.reconcile() == 1 and await svc.reconcile() == 0
            assert len(await tasks.list_tasks()) == 2
            # reprocessing brings nothing back
            await svc.enqueue(note.id, force=True)
            await svc.process_next()
            assert (await svc.status(note.id))["job"]["proposal_count"] == 0 and len(await tasks.list_tasks()) == 2
            # the inquiry reads the same rows
            await notes.add_note("Raw jottings", "Call the plumber")
            reply = await inquiry.answer(inquiry.match("What do I need to do next week?"), tasks=tasks, planner=notes, notepad=store,
                                         access=access_for_owner("t", channel_private=True), now=NOW, timezone="UTC")
            assert "2 confirmed tasks" in reply and "Renew the lab safety certificate" in reply and "1 note has not been processed" in reply
        finally:
            await asyncio.gather(notes.close(), tasks.close(), store.close())

    asyncio.run(go())
    assert sql(dsn, "SELECT count(*) FROM tasks") == [(2,)]


def test_links_and_transcript_snapshots_over_real_stores(dsn, tmp_path):
    from companion_core.meetings.postgres_store import PostgresMeetingStore

    start = datetime(2026, 10, 6, 14, 0, tzinfo=UTC)
    transcript = [{"start": 0.0, "end": 5.0, "text": "I will send the vendor the signed purchase order by Friday."}]

    async def provider():
        async def ask(messages, max_tokens):
            return json.dumps({"items": [{"type": "task", "text": "Send the purchase order", "evidence": ["I will send the vendor the signed purchase order by Friday."],
                                          "stated_time": "Friday", "about_owner": True, "ambiguities": []}]})

        return ask, "scripted-7b"

    async def go():
        notes, tasks, store = await PostgresPlannerStore.connect(dsn), await PostgresTaskStore.connect(dsn), await PostgresNotepadStore.connect(dsn)
        meetings = await PostgresMeetingStore.connect(dsn, audio_dir=tmp_path)
        try:
            async def zone():
                return "UTC"

            svc = NotepadService(store, notes, tasks, zone, provider=provider, meetings=meetings, clock=lambda: NOW)
            m = await meetings.create_meeting(title="Weekly sync", source_filename="a.wav", content_type="audio/wav", audio=b"RIFF", started_at=start)
            sql(dsn, "UPDATE meetings SET duration_seconds = 3600, status = 'transcribing', created_at = %s WHERE id = %s", (NOW, m.id))  # uploaded days later
            note = await notes.add_note("Quick notes", "Chase the vendor.")
            sql(dsn, "UPDATE notes SET created_at = %s, updated_at = %s WHERE id = %s", (start + timedelta(minutes=5), start + timedelta(minutes=9), note.id))
            got = await svc.links_for(note.id)
            assert [(x["meeting_id"], x["state"], x["source"]) for x in got["links"]] == [(m.id, "suggested", "temporal")]
            await svc.links_for(note.id)
            assert sql(dsn, "SELECT count(*) FROM note_meeting_links") == [(1,)]
            await svc.set_link(note.id, m.id, "confirmed")
            await svc.enqueue(note.id, include_meetings=True)  # the transcript does not exist yet: the note is processed alone
            await svc.process_next()
            status = await svc.status(note.id)
            assert status["job"]["meetings"][0]["included"] is False and status["proposals"] == []
            sql(dsn, "UPDATE meetings SET status = 'complete', transcript_segments = %s WHERE id = %s", (json.dumps(transcript), m.id))
            again = await svc.enqueue(note.id, include_meetings=True)
            assert again["created"] is True
            await svc.process_next()
            (p,) = (await svc.status(note.id))["proposals"]
            assert p["evidence_from"] == "transcript" and p["sources"][0]["meeting_id"] == m.id and p["status"] == "pending"
            assert await tasks.list_tasks() == []
            await svc.set_link(note.id, m.id, "rejected")  # unlinking touches neither record
            assert (await notes.get_note(note.id)).body == "Chase the vendor." and (await meetings.get_meeting(m.id)).transcript_segments == transcript
            await svc.accept(p["id"])
            assert len(await tasks.list_tasks()) == 1
        finally:
            await asyncio.gather(notes.close(), tasks.close(), store.close(), meetings.close())

    asyncio.run(go())
    assert Meeting and MeetingJobStatus


# ---- one transcript passage, many notes ----------------------------------------------------------------------------------------------------------

def test_one_transcript_passage_is_one_proposal_in_the_database_whichever_note_finds_it_even_at_the_same_moment(dsn):
    from companion_core.notepad_processing.models import (
        Proposal,
        ProposalStatus,
        fingerprint,
        transcript_source_key,
    )

    quote = "I will send the vendor the signed purchase order by Friday."

    def proposal(j, sensitivity=Privacy.WORK_PRIVATE):
        return Proposal(job_id=j.id, note_id=j.note_id, snapshot_hash=j.snapshot_hash, kind=Kind.TASK, text="Send the purchase order", evidence=quote, span_start=0, span_end=len(quote),
                        fingerprint=fingerprint(quote), source_key=transcript_source_key("m1", "0:05", quote), sensitivity=sensitivity, status=ProposalStatus.PENDING)

    async def go():
        store = await PostgresNotepadStore.connect(dsn)
        try:
            jobs = []
            for i in range(6):
                j, _ = await store.enqueue(job(note_id=f"n{i}", body=f"note {i}"), force=False)
                jobs.append(j)
            claimed = [await store.claim_next(NOW) for _ in jobs]
            assert all(claimed)
            added = await asyncio.gather(*[
                store.complete_job(j.id, [proposal(j, Privacy.SENSITIVE if i == 3 else Privacy.WORK_PRIVATE)], model="m", now=NOW) for i, j in enumerate(jobs)])
            assert sum(added) == 1  # six notes finished together: one proposal
            (only,) = await store.list_proposals()
            assert set(only.associations) == {f"n{i}" for i in range(6)} and only.sensitivity is Privacy.SENSITIVE  # all six retained; the most private level wins
            assert [p.id for p in await store.list_proposals(note_id="n4")] == [only.id]
            # closing notes one by one keeps it pending until the last one goes
            for i in range(5):
                await store.close_for_note(f"n{i}", now=NOW)
            assert (await store.get_proposal(only.id)).status is ProposalStatus.PENDING
            await store.close_for_note("n5", now=NOW)
            assert (await store.get_proposal(only.id)).status is ProposalStatus.DISMISSED
        finally:
            await store.close()

    asyncio.run(go())
    assert sql(dsn, "SELECT count(*) FROM notepad_proposals") == [(1,)] and sql(dsn, "SELECT count(*) FROM notepad_proposal_notes") == [(0,)]


# ---- Phase 47 Brain: derived_from edges from provenance, on the production lifespan -------------------------------------------------------------------

def _boot_brain(dsn, monkeypatch, tmp_path, *, flag):
    import base64

    import httpx
    from companion_core.app import create_app
    from fastapi.testclient import TestClient

    keyfile = tmp_path / "keys.json"
    keyfile.write_text(json.dumps({"active": "one", "keys": {"one": base64.b64encode(b"\x01" * 32).decode()}}))
    keyfile.chmod(0o600)
    monkeypatch.setenv("SECRET_KEY_FILE", str(keyfile))
    monkeypatch.setenv("ACCOUNTS_SERVICE_TOKEN", "t" * 32)
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "5")
    (monkeypatch.setenv("NOTEPAD_PROCESSING_ENABLED", "true") if flag else monkeypatch.delenv("NOTEPAD_PROCESSING_ENABLED", raising=False))
    app = create_app(database_url=dsn, run_meeting_worker_task=False, run_email_dispatch_task=False, run_notepad_runner=False, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    return TestClient(app, headers={"X-Reachy-Service-Token": "t" * 32})


@pytest.mark.parametrize("flag", [False, True], ids=["flag-off", "flag-on"])
def test_the_brain_draws_derived_from_edges_from_real_provenance_with_the_flag_off_or_on(dsn, monkeypatch, tmp_path, flag):
    note_next, note_git, note_other, note_secret = "n-next-week", "n-git", "n-project", "n-secret"
    for nid, title, level in ((note_next, "My Task for next week", "work-private"), (note_git, "GIT", "work-private"), (note_other, "Reachy Project", "work-private"), (note_secret, "Therapy", "sensitive")):
        sql(dsn, "INSERT INTO notes (id, title, body, created_at, updated_at, sensitivity) VALUES (%s,%s,%s,now(),now(),%s)", (nid, title, "body of " + title, level))
    for tid, text in (("t-clickhouse", "refactor clickhouse migration"), ("t-gitlab", "spin up gitlab repo"), ("t-from-secret", "task from a restricted note"), ("t-plain", "task with no provenance")):
        sql(dsn, "INSERT INTO tasks (id, text, status, created_at) VALUES (%s,%s,'open',now())", (tid, text))
    for tid, nid, pid in (("t-clickhouse", note_next, "prop-clickhouse"), ("t-gitlab", note_git, "prop-gitlab"), ("t-from-secret", note_secret, "prop-secret")):
        sql(dsn, "INSERT INTO notepad_provenance VALUES ('task',%s,%s,%s,'0123456789abcdef',now())", (tid, nid, pid))
    sql(dsn, "INSERT INTO notepad_proposals (id, job_id, note_id, snapshot_hash, kind, text, evidence, span_start, span_end, evidence_from, status, fingerprint, prompt_version, sensitivity, created_at) "
             "VALUES ('pending-1','j',%s,'h','task','a pending suggestion','x',0,1,'note','pending','fp','v','work-private',now())", (note_other,))
    ids = ",".join(f"note:{n}" for n in (note_next, note_git, note_other, note_secret)) + "," + ",".join(f"task:{t}" for t in ("t-clickhouse", "t-gitlab", "t-from-secret", "t-plain"))
    expected = {("task:t-clickhouse", f"note:{note_next}", "derived_from:prop-clickhouse"), ("task:t-gitlab", f"note:{note_git}", "derived_from:prop-gitlab")}
    seen = []
    for _boot in range(2):  # the second boot is a restart: the edges come from the database, not from memory
        with _boot_brain(dsn, monkeypatch, tmp_path, flag=flag) as client:
            assert (client.app.state.notepad_service is not None) is flag  # the flag governs processing only
            body = client.get("/brain/edges", params={"ids": ids}).json()
            assert {(e["from"], e["to"], e["id"]) for e in body["edges"]} == expected
            assert client.get("/brain/summary").json()["edges"] == 2
            blob = json.dumps(body) + json.dumps(client.get("/brain/summary").json())
            assert "prop-secret" not in blob and "t-from-secret" not in blob and note_secret not in blob and "pending" not in blob.lower()
            assert client.get("/brain/edges", params={"ids": ids}).json() == body  # repeated: identical, no duplicates
            seen.append(body)
            types = {n["id"].split(":")[0] for n in client.get("/brain/nodes", params={"limit": 200}).json()["nodes"]}
            assert "proposal" not in types
    assert seen[0] == seen[1]
    assert sql(dsn, "SELECT count(*) FROM notepad_provenance") == [(3,)] and sql(dsn, "SELECT count(*) FROM tasks") == [(4,)]  # reading wrote nothing
    # deleting the note hides its edge without touching the provenance row
    sql(dsn, "DELETE FROM notes WHERE id = %s", (note_git,))
    with _boot_brain(dsn, monkeypatch, tmp_path, flag=flag) as client:
        assert {(e["from"], e["to"]) for e in client.get("/brain/edges", params={"ids": ids}).json()["edges"]} == {("task:t-clickhouse", f"note:{note_next}")}
        assert client.get("/brain/summary").json()["edges"] == 1
    assert sql(dsn, "SELECT count(*) FROM notepad_provenance") == [(3,)]
