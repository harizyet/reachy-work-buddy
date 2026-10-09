"""Phase 44E follow-up: the knowledge shadow under the PRODUCTION lifespan on a disposable Postgres (DATABASE_MIGRATION_TEST_URL; synthetic data only).

The app is built the way production builds it (no injected stores, `database_url`, one shared bounded pool); the shadow is switched on by its environment
flag. What is proved: the shadow uses the shared pool, never changes the foreground (prompts, model, replies, database state), is bounded under saturation,
isolated from database faults, stops cleanly with the service, and a restart continues the same aggregate file with a reconciled funnel."""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx
import psycopg
import pytest
from companion_core.app import create_app
from companion_core.knowledge.shadow import KnowledgeShadow
from companion_core.knowledge.shadow_telemetry import ShadowTelemetry, reconcile
from fastapi.testclient import TestClient

from shared.protocols.accounts import SERVICE_HEADER

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "knowledge_retrieval"))
from kbench.corpus import build_corpus
from kbench.pg_env import build_pg_corpus, hashing_embed_384

needs_db = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
TURN = {"conversation_id": "c1", "channel": "web"}
KNOWLEDGE = ["What are my open tasks?", "Who owns the Quill message queue?", "What does the Beacon Analytics vendor note say?"]
CHITCHAT = ["Tell me a joke", "What is the capital of France?"]
POOL_MAX = 5


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A migrated, seeded and indexed disposable database, and the environment a production core would have."""
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    spec = asyncio.run(build_corpus()).spec
    env = asyncio.run(build_pg_corpus(spec, hashing_embed_384, "hashing-bag-of-words-384"))
    keyfile = tmp_path / "keys.json"
    keyfile.write_text(json.dumps({"active": "one", "keys": {"one": base64.b64encode(b"\x01" * 32).decode()}}))
    keyfile.chmod(0o600)
    monkeypatch.setenv("SECRET_KEY_FILE", str(keyfile))
    monkeypatch.setenv("ACCOUNTS_SERVICE_TOKEN", "t" * 32)
    monkeypatch.setenv("DB_POOL_MAX_SIZE", str(POOL_MAX))
    monkeypatch.setenv("KNOWLEDGE_SHADOW_LOG_PATH", str(tmp_path / "shadow.jsonl"))
    monkeypatch.delenv("KNOWLEDGE_SHADOW_ENABLED", raising=False)
    box = type("W", (), {})()
    box.dsn, box.root, box.env, box.log, box.calls = env.dsn, root, env, tmp_path / "shadow.jsonl", []
    box.idle = 0
    with psycopg.connect(root, autocommit=True) as conn:  # the seeding pools are finished with: end their connections so the app's are the only ones counted
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (env.name,))
    try:
        yield box
    finally:  # the seeding pools belong to a finished event loop: drop the database directly
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(psycopg.sql.Identifier(env.name)))


def fingerprint(world) -> str:
    """A hash of every authoritative table (not the derived index, not read stamps), to prove the shadow changed nothing."""
    import hashlib

    parts = []
    with psycopg.connect(world.dsn) as conn:
        for table in ("memories", "document_chunks", "meetings", "notes", "tasks", "reminders"):
            parts.append(conn.execute(f"SELECT coalesce(md5(string_agg((to_jsonb(t) - ARRAY['last_accessed','updated_at','embedding'])::text, '|' ORDER BY t.id)), '') FROM {table} t").fetchone()[0])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def backends(world) -> int:
    name = psycopg.conninfo.conninfo_to_dict(world.dsn)["dbname"]
    with psycopg.connect(world.root, autocommit=True) as conn:
        return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,)).fetchone()[0]


def boot(world, *, shadow: bool, reply: str = "A normal answer.", monkeypatch=None):
    world.calls = calls = []

    def llm(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    if monkeypatch is not None:
        (monkeypatch.setenv if shadow else monkeypatch.delenv)("KNOWLEDGE_SHADOW_ENABLED", *(["true"] if shadow else []), **({} if shadow else {"raising": False}))
    return create_app(database_url=world.dsn, run_meeting_worker_task=False, run_email_dispatch_task=False, llm_transport=httpx.MockTransport(llm))


def authed(app) -> TestClient:
    return TestClient(app, headers={SERVICE_HEADER: "t" * 32})


def ask(client, text, session="s"):
    return client.post("/conversation", json={**TURN, "session_id": session, "text": text})


def configure(client):
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})


def totals(world) -> dict:
    return ShadowTelemetry.read_totals(str(world.log)) if world.log.exists() else {"counts": {}, "evaluated_qualifying": 0}


@needs_db
def test_the_shadow_exists_only_when_enabled_and_then_uses_the_one_shared_bounded_pool(world, monkeypatch):
    with authed(boot(world, shadow=False, monkeypatch=monkeypatch)) as client:
        assert client.app.state.knowledge_shadow is None
    app = boot(world, shadow=True, monkeypatch=monkeypatch)
    with authed(app) as client:
        configure(client)
        shadow = app.state.knowledge_shadow
        assert isinstance(shadow, KnowledgeShadow) and shadow.retriever.search._pool is app.state.task_store._pool  # no pool of its own
        for i, q in enumerate(KNOWLEDGE * 4):
            ask(client, q, f"p{i}")
        client.portal.call(shadow.drain)
        assert backends(world) <= POOL_MAX  # the shadow added no connections beyond the shared pool's bound
    assert backends(world) == 0  # shutdown released everything


@needs_db
def test_foreground_prompts_model_replies_and_database_state_are_identical_with_the_shadow_on_and_off(world, monkeypatch):
    outcomes = []
    for enabled in (False, True):
        app = boot(world, shadow=enabled, monkeypatch=monkeypatch)
        before = fingerprint(world)
        with authed(app) as client:
            configure(client)
            replies = [ask(client, q, f"f{i}").json() for i, q in enumerate(KNOWLEDGE + CHITCHAT)]
            assert all("reply" in r for r in replies)  # a vacuous comparison of identical errors would prove nothing
            if enabled:
                client.portal.call(app.state.knowledge_shadow.drain)
        assert fingerprint(world) == before  # reads only: no authoritative table changed
        outcomes.append((replies, [(c["model"], c["messages"]) for c in world.calls]))
    assert outcomes[0] == outcomes[1]  # same replies, same model, byte-identical prompts: nothing from the shadow reached the answer path
    assert not any("<evidence" in m["content"] for _, msgs in outcomes[1][1] for m in msgs)


@needs_db
def test_only_qualifying_knowledge_questions_are_evaluated_and_the_funnel_reconciles(world, monkeypatch):
    app = boot(world, shadow=True, monkeypatch=monkeypatch)
    with authed(app) as client:
        configure(client)
        for i, q in enumerate(KNOWLEDGE + CHITCHAT):
            ask(client, q, f"q{i}")
        client.portal.call(app.state.knowledge_shadow.drain)
    t = totals(world)
    assert t["evaluated_qualifying"] == 3 and t["counts"]["not_qualifying"] == 2 and t["counts"]["attempted"] == 5
    assert reconcile(t["counts"]) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}


@needs_db
def test_queue_saturation_drops_oldest_never_slows_the_reply_and_every_job_is_accounted_for(world, monkeypatch):
    app = boot(world, shadow=True, monkeypatch=monkeypatch)
    with authed(app) as client:
        configure(client)
        shadow = app.state.knowledge_shadow
        shadow.queue_size, shadow.timeout_seconds = 2, 0.3

        async def slow(turn):
            await asyncio.sleep(5)

        shadow._measure = slow
        started = time.perf_counter()
        for i in range(8):
            assert ask(client, "Who owns the Quill message queue?", f"sat{i}").status_code == 200
        assert time.perf_counter() - started < 6  # eight replies, none waited for a five-second job
        client.portal.call(shadow.drain)
    c = totals(world)["counts"]
    assert c["dropped_busy"] >= 1 and c["failed_timeout"] >= 1 and totals(world)["evaluated_qualifying"] == 0
    assert reconcile(c) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}


@needs_db
def test_a_shadow_database_fault_is_isolated_and_the_pool_stays_healthy(world, monkeypatch):
    app = boot(world, shadow=True, monkeypatch=monkeypatch)
    with authed(app) as client:
        configure(client)
        shadow = app.state.knowledge_shadow
        shadow.timeout_seconds = 0.4
        pool = app.state.task_store._pool
        real = shadow.retriever.search.lexical

        async def raises(*a, **k):
            raise psycopg.OperationalError("simulated outage")

        async def hangs(*a, **k):
            async with pool.connection() as conn:
                await conn.execute("SELECT pg_sleep(5)")  # a stuck query inside the shadow's job

        for fault in (raises, hangs):
            shadow.retriever.search.lexical = fault
            assert ask(client, "Who owns the Quill message queue?", f"x{fault.__name__}").status_code == 200
            client.portal.call(shadow.drain)
            assert ask(client, "What are my open tasks?", f"y{fault.__name__}").status_code == 200  # the foreground still reads the same database
        shadow.retriever.search.lexical = real
        # kill every other backend, as a database restart would: the pool reconnects, the foreground and a later shadow job both work
        with psycopg.connect(world.root, autocommit=True) as conn:
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                         (psycopg.conninfo.conninfo_to_dict(world.dsn)["dbname"],))
        assert ask(client, "What are my open tasks?", "after-kill").status_code == 200
        ask(client, "Who owns the Quill message queue?", "after-kill-2")
        client.portal.call(shadow.drain)
        assert backends(world) <= POOL_MAX
    c = totals(world)["counts"]
    assert c["failed_error"] >= 1 and c["failed_timeout"] >= 1
    assert reconcile(c) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}


@needs_db
def test_shutdown_stops_the_worker_and_releases_the_pool_and_a_restart_continues_the_same_file(world, monkeypatch):
    app = boot(world, shadow=True, monkeypatch=monkeypatch)
    with authed(app) as client:
        configure(client)
        shadow = app.state.knowledge_shadow
        assert shadow._terms  # the vocabulary was primed from the owner's records at start
        shadow.queue_size, shadow.timeout_seconds = 5, 0.5

        async def slow(turn):
            await asyncio.sleep(3)

        shadow._measure = slow
        for i in range(4):
            ask(client, "Who owns the Quill message queue?", f"st{i}")
    assert backends(world) == 0 and (shadow._worker is None or shadow._worker.done())  # stopped with the service
    first = totals(world)
    assert reconcile(first["counts"]) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}  # what was queued at stop is counted as discarded or timed out
    app2 = boot(world, shadow=True, monkeypatch=monkeypatch)
    with authed(app2) as client:
        configure(client)
        ask(client, "Who owns the Quill message queue?", "again")
        client.portal.call(app2.state.knowledge_shadow.drain)
    second = totals(world)
    assert second["evaluated_qualifying"] == first["evaluated_qualifying"] + 1 and second["counts"]["attempted"] == first["counts"]["attempted"] + 1
    assert reconcile(second["counts"]) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}
    assert backends(world) == 0


@needs_db
def test_a_shadow_that_cannot_start_or_stop_does_not_stop_the_service(world, monkeypatch):
    async def broken(self):
        raise RuntimeError("shadow cannot start")

    monkeypatch.setattr(KnowledgeShadow, "start", broken)
    monkeypatch.setattr(KnowledgeShadow, "stop", broken)
    app = boot(world, shadow=True, monkeypatch=monkeypatch)
    with authed(app) as client:
        configure(client)
        assert ask(client, "What are my open tasks?").status_code == 200
    assert backends(world) == 0  # the service still shut down and released its pool
