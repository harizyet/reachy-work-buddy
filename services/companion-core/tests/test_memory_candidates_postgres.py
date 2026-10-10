"""Phase 44F on real PostgreSQL (opt-in: DATABASE_MIGRATION_TEST_URL, a disposable server with pgvector): migration 028 and its rollback script, the structural guarantees (no candidate text after a
decision, one memory per candidate, no trigger or foreign key into memories or the index), the real store under concurrency and crash recovery, and the PRODUCTION lifespan with the flags,
the hub privacy lookup (fail closed), the review routes and a restart. Synthetic data only; nothing here is deployed."""

import asyncio
import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import pytest
from companion_core.app import create_app
from companion_core.memory import candidate_service as cs
from companion_core.memory.candidates import (
    PostgresCandidateStore,
    new_candidate,
)
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.migrations.__main__ import upgrade
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.secrets import Keyring
from fastapi.testclient import TestClient

from shared.models.memory import MemoryType
from shared.models.response import Privacy
from shared.protocols.accounts import SERVICE_HEADER
from shared.protocols.memory_candidates_api import PRIVACY_STATE

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
KEYS = Keyring("one", {"one": b"\x01" * 32})
ROLLBACK = Path(__file__).resolve().parents[3] / "deploy" / "homelab" / "rollback-028.sql"
SAY = "I prefer written summaries to spoken ones."


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


def row(dsn, **over):
    base = {"id": str(uuid4()), "text": "t", "rule_id": "r", "rule_version": 1, "channel": "web", "proposed_type": "profile", "sensitivity": "work-private", "status": "pending", "digest": "d", "digest_key_id": "one",
                "created_at": datetime.now(UTC), "expires_at": datetime.now(UTC) + timedelta(days=14), "memory_id": None, "decided_at": None}
    base.update(over)
    cols = ", ".join(base)
    sql(dsn, f"INSERT INTO memory_candidates ({cols}) VALUES ({', '.join(['%s'] * len(base))})", list(base.values()))


# ---- migration 028 ----------------------------------------------------------------------------------------------------------------------------

def test_the_migration_creates_only_candidate_bookkeeping_with_structural_guarantees(dsn):
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("028_memory_candidates",)]
    assert {r[0] for r in sql(dsn, "SELECT tablename FROM pg_tables WHERE tablename LIKE 'memory_candidate%'")} == {"memory_candidates", "memory_candidate_suppressions", "memory_candidate_counters"}
    assert sql(dsn, "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'memory_candidates'::regclass AND NOT tgisinternal") == [(0,)]  # no trigger: nothing reaches the index or outbox
    assert sql(dsn, "SELECT count(*) FROM pg_constraint WHERE conrelid IN ('memory_candidates'::regclass, 'memory_candidate_suppressions'::regclass) AND contype = 'f'") == [(0,)]
    row(dsn)  # a well-formed pending row
    for bad in ({"text": None}, {"status": "rejected", "text": "kept"}, {"status": "suppressed", "text": "kept"}, {"status": "accepted", "text": None}, {"text": "x" * 401},
                {"status": "accepting", "text": None}, {"status": "bogus"}, {"sensitivity": "secret"}, {"proposed_type": "other"}):
        with pytest.raises(psycopg.errors.CheckViolation):
            row(dsn, **bad)  # a rejected, suppressed or accepted candidate cannot keep text; an accepted one needs its memory; pending needs text
    row(dsn, status="rejected", text=None, decided_at=datetime.now(UTC))
    row(dsn, status="accepted", text=None, memory_id="m1", decided_at=datetime.now(UTC))
    sql(dsn, "INSERT INTO memories VALUES ('m1','working','fact','candidate:abc',NULL,1.0,'work-private',now(),NULL,NULL,NULL)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        sql(dsn, "INSERT INTO memories VALUES ('m2','working','fact again','candidate:abc',NULL,1.0,'work-private',now(),NULL,NULL,NULL)")  # one memory per candidate, in the database itself
    sql(dsn, "INSERT INTO memories VALUES ('m3','working','a','conversation',NULL,1.0,'work-private',now(),NULL,NULL,NULL)")
    sql(dsn, "INSERT INTO memories VALUES ('m4','working','b','conversation',NULL,1.0,'work-private',now(),NULL,NULL,NULL)")  # other sources are unconstrained
    upgrade(dsn, KEYS)  # a repeat changes nothing


def test_candidate_rows_never_reach_the_knowledge_outbox_or_index_but_the_accepted_memory_does(dsn):
    before = sql(dsn, "SELECT count(*) FROM knowledge_outbox")[0][0]
    row(dsn)
    row(dsn, status="rejected", text=None, decided_at=datetime.now(UTC))
    assert sql(dsn, "SELECT count(*) FROM knowledge_outbox") == [(before,)] and sql(dsn, "SELECT count(*) FROM knowledge_items") == [(0,)]
    sql(dsn, "INSERT INTO memories VALUES ('m1','working','fact','candidate:abc',NULL,1.0,'work-private',now(),NULL,NULL,NULL)")
    assert sql(dsn, "SELECT source_type, source_id FROM knowledge_outbox") == [("memory", "m1")]  # only the owner-approved memory is queued (and only matters if indexing is on)


def test_the_rollback_script_removes_the_bookkeeping_keeps_accepted_memories_and_the_migration_can_run_again(dsn):
    row(dsn)
    sql(dsn, "INSERT INTO memories VALUES ('m1','working','accepted fact','candidate:abc',NULL,1.0,'work-private',now(),NULL,NULL,NULL)")
    with psycopg.connect(dsn) as conn:
        conn.execute(ROLLBACK.read_text())
        conn.commit()
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("027_knowledge_index",)]
    assert sql(dsn, "SELECT count(*) FROM pg_tables WHERE tablename LIKE 'memory_candidate%'") == [(0,)]
    assert sql(dsn, "SELECT count(*) FROM pg_indexes WHERE indexname = 'memories_candidate_source_uq'") == [(0,)]
    assert sql(dsn, "SELECT content FROM memories WHERE id = 'm1'") == [("accepted fact",)]  # the memory the owner accepted stays
    upgrade(dsn, KEYS)  # applying again after a rollback or a restore works
    assert sql(dsn, "SELECT version_num FROM alembic_version") == [("028_memory_candidates",)] and sql(dsn, "SELECT count(*) FROM memory_candidates") == [(0,)]
    assert sql(dsn, "SELECT content FROM memories WHERE id = 'm1'") == [("accepted fact",)]


# ---- the real store ------------------------------------------------------------------------------------------------------------------------------

DIGESTER = cs.KeyedDigester(KEYS)


def make(text, now, digester=DIGESTER, **over):
    k, d = digester.active(text)
    args = {"text": text, "rule_id": "preference.prefer", "rule_version": 1, "conversation_id": "c1", "session_id": "s", "turn_index": 1, "channel": "web", "proposed_type": MemoryType.PROFILE,
                "proposed_scope": None, "sensitivity": Privacy.WORK_PRIVATE, "digest": d, "digest_key_id": k, "now": now}
    args.update(over)
    return new_candidate(**args), digester.lookup(text)


def test_caps_duplicates_suppression_and_concurrent_claims_on_the_real_store(dsn):
    async def go():
        store = await PostgresCandidateStore.connect(dsn)
        now = datetime(2026, 10, 10, 9, 5, tzinfo=UTC)
        made = []
        for n in range(7):
            c, lookup = make(f"I prefer thing{n} over the rest.", now + timedelta(minutes=n))
            got, reason = await store.create(c, lookup)
            made.append((got is not None, reason))
        assert [m[0] for m in made] == [True] * 5 + [False] * 2 and made[-1][1] == "hourly_cap"
        c, lookup = make("I prefer thing0 over the rest.", now + timedelta(minutes=9))
        assert (await store.create(c, lookup))[1] == "duplicate"
        first = (await store.list_pending(now + timedelta(minutes=10)))[0]
        assert (await store.reject(first.id, suppress=True, now=now)).outcome == "done"
        c, lookup = make(f"I prefer thing{4} over the rest.", now + timedelta(hours=2))  # suppressed or duplicate: never created again
        assert (await store.create(c, lookup))[0] is None
        left = (await store.list_pending(now + timedelta(minutes=10)))[0]
        claims = await asyncio.gather(*[store.claim_accept(left.id, text=left.text, type=left.proposed_type, scope=None, sensitivity=left.sensitivity, memory_expires_at=None,
                                                           edited=False, now=now) for _ in range(10)])
        assert sorted(c.outcome for c in claims) == ["claimed"] + ["in_progress"] * 9
        await store.close()

    asyncio.run(go())


def test_concurrent_accepts_crash_recovery_and_retention_on_the_real_stores(dsn):
    async def go():
        store, memory, planner = await PostgresCandidateStore.connect(dsn), await PostgresMemoryStore.connect(dsn), await PostgresPlannerStore.connect(dsn)
        clock = [datetime.now(UTC)]
        service = cs.CandidateService(store, memory, planner, clock=lambda: clock[0])
        c, lookup = make(SAY, clock[0])
        await store.create(c, lookup)
        results = await asyncio.gather(*[service.accept(c.id) for _ in range(12)], return_exceptions=True)
        assert any(isinstance(r, dict) for r in results) and all(isinstance(r, (dict, cs.CandidateError)) for r in results)
        again = await service.accept(c.id)
        assert again["candidate"]["status"] == "accepted" and len(await memory.list_memories()) == 1
        assert sql(dsn, "SELECT count(*) FROM action_receipts WHERE action_type = 'memory.created'") == [(1,)]
        assert sql(dsn, "SELECT text, status FROM memory_candidates WHERE id = %s", (c.id,)) == [(None, "accepted")]
        # crash after the claim and after the memory was written
        c2, lookup2 = make("I always take notes by hand.", clock[0])
        await store.create(c2, lookup2)
        claim = await store.claim_accept(c2.id, text=c2.text, type=c2.proposed_type, scope=None, sensitivity=c2.sensitivity, memory_expires_at=None, edited=False, now=clock[0])
        assert claim.outcome == "claimed"
        await memory.add_memory(content=c2.text, source=f"candidate:{c2.id}")
        with pytest.raises(psycopg.errors.UniqueViolation):
            await memory.add_memory(content="duplicate attempt", source=f"candidate:{c2.id}")  # the database itself refuses a second memory
        clock[0] += timedelta(minutes=10)
        assert await service.reconcile() == 1 and await service.reconcile() == 0
        assert len(await memory.list_memories()) == 2 and sql(dsn, "SELECT count(*) FROM action_receipts WHERE action_type = 'memory.created'") == [(2,)]
        # retention: forgotten memory clears the pointer; hard-deleted memory removes the row; pending expires with a count
        c3, lookup3 = make("I usually review notes on Friday.", clock[0])
        await store.create(c3, lookup3)
        await memory.forget((await memory.get_by_source(f"candidate:{c.id}")).id)
        clock[0] += timedelta(days=15)
        out = await service.maintain()
        assert out["expired"] == 1 and out["provenance_cleared"] == 1
        assert sql(dsn, "SELECT conversation_id, session_id, turn_index FROM memory_candidates WHERE id = %s", (c.id,)) == [(None, None, None)]
        sql(dsn, "DELETE FROM memories WHERE source = %s", (f"candidate:{c2.id}",))
        assert (await service.maintain())["rows_removed_with_memory"] == 1
        assert (await store.counters(datetime(2000, 1, 1, tzinfo=UTC)))["expired"] == 1
        for part in (store, memory, planner):
            await part.close()

    asyncio.run(go())


# ---- the production lifespan -----------------------------------------------------------------------------------------------------------------------

def boot(dsn, monkeypatch, tmp_path, *, enabled=True, capture=True, hub_state=None, model_reply="An ordinary reply."):
    keyfile = tmp_path / "keys.json"
    keyfile.write_text(json.dumps({"active": "one", "keys": {"one": base64.b64encode(b"\x01" * 32).decode()}}))
    keyfile.chmod(0o600)
    monkeypatch.setenv("SECRET_KEY_FILE", str(keyfile))
    monkeypatch.setenv("ACCOUNTS_SERVICE_TOKEN", "t" * 32)
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "5")
    for name, on in ((cs.ENABLED_FLAG, enabled), (cs.CAPTURE_FLAG, capture)):
        (monkeypatch.setenv(name, "true") if on else monkeypatch.delenv(name, raising=False))
    asked = {"privacy": 0, "model": []}

    def hub(request: httpx.Request) -> httpx.Response:
        if request.url.path == PRIVACY_STATE:
            asked["privacy"] += 1
            if hub_state == "error":
                return httpx.Response(500, json={})
            return httpx.Response(200, json={"privacy_mode": False} if hub_state is None else hub_state)
        return httpx.Response(200, json={})

    def llm(request: httpx.Request) -> httpx.Response:
        asked["model"].append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": model_reply}}]})

    app = create_app(database_url=dsn, run_meeting_worker_task=False, run_email_dispatch_task=False, llm_transport=httpx.MockTransport(llm), transport=httpx.MockTransport(hub))
    return TestClient(app, headers={SERVICE_HEADER: "t" * 32}), asked


def say(client, text, session="s", **extra):
    body = {"session_id": session, "conversation_id": "c1", "channel": "web", "text": text, **extra}
    reply = client.post("/conversation", json=body).json()
    capture = client.app.state.candidate_capture
    if capture is not None:
        client.portal.call(capture.drain)
    return reply


def configure(client):
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})


def test_flags_off_build_nothing_and_the_routes_do_not_exist(dsn, monkeypatch, tmp_path):
    client, asked = boot(dsn, monkeypatch, tmp_path, enabled=False, capture=False)
    with client:
        configure(client)
        assert client.app.state.candidate_service is None and client.app.state.candidate_capture is None
        assert client.get("/memory-candidates").status_code == 404
        say(client, SAY)
    assert asked["privacy"] == 0 and sql(dsn, "SELECT count(*) FROM memory_candidates") == [(0,)]


def test_the_whole_workflow_on_the_production_lifespan_with_a_restart(dsn, monkeypatch, tmp_path):
    client, asked = boot(dsn, monkeypatch, tmp_path)
    memories_before = sql(dsn, "SELECT count(*) FROM memories")
    with client:
        configure(client)
        assert client.app.state.candidate_service.store._pool is client.app.state.task_store._pool  # the one shared bounded pool
        assert say(client, SAY)["reply"] == "An ordinary reply." and asked["privacy"] == 1
        assert sql(dsn, "SELECT count(*) FROM memories") == memories_before  # a candidate is not a memory
        (c,) = client.get("/memory-candidates").json()["candidates"]
        assert c["text"] == SAY
        # a recall of the same words finds nothing: the candidate table is invisible to recall and to every later prompt
        assert client.get("/memories/recall", params={"q": "summaries"}).json() == []
        say(client, "What do I prefer?", session="q")
        assert "written summaries" not in json.dumps(asked["model"][1:])
        done = client.post(f"/memory-candidates/{c['id']}/accept", json={"text": SAY.replace("written", "short written")}).json()
        assert done["candidate"]["status"] == "edited-accepted" and done["memory"]["content"].startswith("I prefer short written")
        assert client.post(f"/memory-candidates/{c['id']}/accept", json={}).json()["memory"]["id"] == done["memory"]["id"]
    assert sql(dsn, "SELECT count(*) FROM memories WHERE source = %s", (f"candidate:{c['id']}",)) == [(1,)]
    assert sql(dsn, "SELECT count(*) FROM action_receipts WHERE action_type = 'memory.created'") == [(1,)]
    assert sql(dsn, "SELECT text, memory_id IS NOT NULL FROM memory_candidates WHERE id = %s", (c["id"],)) == [(None, True)]
    # a restart finds the same state and recovers an interrupted accept
    c2 = make("I always take notes by hand.", datetime.now(UTC))[0]
    client2, _ = boot(dsn, monkeypatch, tmp_path)
    with client2:
        configure(client2)
        asyncio.run(_seed_crash(dsn, c2))
        assert client2.app.state.candidate_service is not None
        assert asyncio.run(_stale_recover(client2, dsn, c2)) == 1
    assert sql(dsn, "SELECT count(*) FROM memories WHERE source = %s", (f"candidate:{c2.id}",)) == [(1,)]


async def _seed_crash(dsn, c2):
    store = await PostgresCandidateStore.connect(dsn)
    await store.create(c2, [(c2.digest_key_id, c2.digest)])
    old = datetime.now(UTC) - timedelta(minutes=30)
    await store.claim_accept(c2.id, text=c2.text, type=c2.proposed_type, scope=None, sensitivity=c2.sensitivity, memory_expires_at=None, edited=False, now=old)
    await store.close()


async def _stale_recover(client, dsn, c2):
    store = await PostgresCandidateStore.connect(dsn)
    memory = await PostgresMemoryStore.connect(dsn)
    planner = await PostgresPlannerStore.connect(dsn)
    n = await cs.CandidateService(store, memory, planner).reconcile()
    for part in (store, memory, planner):
        await part.close()
    return n


@pytest.mark.parametrize(("state", "why"), [({"privacy_mode": True}, "privacy mode on"), ({}, "field missing"), ("error", "hub error"), ({"privacy_mode": "false"}, "not a boolean")])
def test_privacy_mode_on_or_unknown_on_the_hub_disables_capture(dsn, monkeypatch, tmp_path, state, why):
    client, asked = boot(dsn, monkeypatch, tmp_path, hub_state=state)
    with client:
        configure(client)
        say(client, SAY)
        assert asked["privacy"] == 1, why
    assert sql(dsn, "SELECT count(*) FROM memory_candidates") == [(0,)] and sql(dsn, "SELECT count(*) FROM memories") == [(0,)]


def test_a_missing_keyring_keeps_capture_off_but_review_works(dsn, monkeypatch, tmp_path):
    client, _ = boot(dsn, monkeypatch, tmp_path)
    monkeypatch.setattr(cs, "KeyedDigester", lambda keyring: (_ for _ in ()).throw(RuntimeError("keyring unavailable")))  # what digester_from_env turns into "capture stays off"
    with client:
        configure(client)
        assert client.app.state.candidate_service is not None and client.app.state.candidate_capture is None
        say(client, SAY)
        assert client.get("/memory-candidates").json() == {"candidates": [], "capture_enabled": False}
