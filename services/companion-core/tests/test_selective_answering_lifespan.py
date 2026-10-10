"""Phase 44E integration under the PRODUCTION lifespan on a disposable Postgres (DATABASE_MIGRATION_TEST_URL; synthetic data only): the flag matrix, the shared bounded pool, feature-flag rollback
(on, off, on), an index fault giving the fixed reply with no model answer and recovering afterwards, and no change to authoritative data. The model is a mock; nothing here is deployed."""

import asyncio
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx
import psycopg
import pytest
from companion_core.app import ACTION_BOUNDARY_INSTRUCTION, create_app
from companion_core.knowledge import selective_answer as sa
from fastapi.testclient import TestClient

from shared.protocols.accounts import SERVICE_HEADER

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "knowledge_retrieval"))
from kbench.corpus import build_corpus
from kbench.pg_env import build_pg_corpus, hashing_embed_384

needs_db = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
TURN = {"conversation_id": "c1", "channel": "web"}
Q = "Who owns the Quill message queue?"
POOL_MAX = 5
LLM_ANSWER = "LLM-ANSWER-WITHOUT-EVIDENCE"


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    spec = asyncio.run(build_corpus()).spec
    env = asyncio.run(build_pg_corpus(spec, hashing_embed_384, "hashing-bag-of-words-384"))
    keyfile = tmp_path / "keys.json"
    keyfile.write_text(json.dumps({"active": "one", "keys": {"one": base64.b64encode(b"\x01" * 32).decode()}}))
    keyfile.chmod(0o600)
    monkeypatch.setenv("SECRET_KEY_FILE", str(keyfile))
    monkeypatch.setenv("ACCOUNTS_SERVICE_TOKEN", "t" * 32)
    monkeypatch.setenv("DB_POOL_MAX_SIZE", str(POOL_MAX))
    for name in (sa.RETRIEVAL_FLAG, sa.SELECTIVE_FLAG, "KNOWLEDGE_SHADOW_ENABLED", "KNOWLEDGE_INDEXING_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    box = type("W", (), {})()
    box.dsn, box.root, box.env, box.calls, box.answer_calls = env.dsn, root, env, [], 0
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (env.name,))
    try:
        yield box
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(psycopg.sql.Identifier(env.name)))


def fingerprint(world) -> str:
    parts = []
    with psycopg.connect(world.dsn) as conn:
        for table in ("memories", "document_chunks", "meetings", "notes", "tasks", "reminders"):
            parts.append(conn.execute(f"SELECT coalesce(md5(string_agg((to_jsonb(t) - ARRAY['last_accessed','updated_at','embedding'])::text, '|' ORDER BY t.id)), '') FROM {table} t").fetchone()[0])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def backends(world) -> int:
    name = psycopg.conninfo.conninfo_to_dict(world.dsn)["dbname"]
    with psycopg.connect(world.root, autocommit=True) as conn:
        return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,)).fetchone()[0]


def boot(world, monkeypatch, *, retrieval: bool, selective: bool):
    world.calls, world.answer_calls = [], 0

    def llm(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        world.calls.append(body)
        if any(m.get("content") == ACTION_BOUNDARY_INSTRUCTION for m in body["messages"]):
            world.answer_calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": LLM_ANSWER}}]})

    for name, on in ((sa.RETRIEVAL_FLAG, retrieval), (sa.SELECTIVE_FLAG, selective)):
        (monkeypatch.setenv(name, "true") if on else monkeypatch.delenv(name, raising=False))
    app = create_app(database_url=world.dsn, run_meeting_worker_task=False, run_email_dispatch_task=False, llm_transport=httpx.MockTransport(llm))
    return TestClient(app, headers={SERVICE_HEADER: "t" * 32})


def ask(client, text, session="s"):
    return client.post("/conversation", json={**TURN, "session_id": session, "text": text}).json()


def configure(client):
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})


@needs_db
def test_the_flag_matrix_and_the_answer_under_the_production_lifespan(world, monkeypatch):
    before = fingerprint(world)
    for retrieval, selective in ((False, False), (True, False), (False, True)):
        with boot(world, monkeypatch, retrieval=retrieval, selective=selective) as client:
            configure(client)
            assert client.app.state.selective_answerer is None
            assert ask(client, Q)["reply"] == LLM_ANSWER and world.answer_calls == 1  # the ordinary path, no retrieved material anywhere in the prompt
            assert not any("<evidence" in m["content"] for call in world.calls for m in call["messages"])
    with boot(world, monkeypatch, retrieval=True, selective=True) as client:
        configure(client)
        answerer = client.app.state.selective_answerer
        assert isinstance(answerer, sa.SelectiveAnswerer) and answerer.retriever.search._pool is client.app.state.task_store._pool  # the one shared pool
        started = time.perf_counter()
        # the production index is populated by build_pg_corpus; the vocabulary primed at startup makes the corpus's own terms anchors
        got = ask(client, Q)
        elapsed = (time.perf_counter() - started) * 1000
        assert got["reply"].startswith("The owner of the Quill message queue is Tomas Weber [E1].") and world.answer_calls == 0
        assert got["privacy"] == "work-private"
        assert ask(client, "Tell me a joke", "other")["reply"] == LLM_ANSWER  # ineligible: unchanged
        assert answerer.stats.counts["answered"] == 1 and backends(world) <= POOL_MAX
        print(f"\nselective answer latency over the production lifespan: {elapsed:.0f} ms")
    assert backends(world) == 0
    assert fingerprint(world) == before  # no authoritative record was changed by any of it


@needs_db
def test_rollback_off_then_on_again_and_an_index_fault_gives_the_fixed_reply_with_no_model_answer(world, monkeypatch):
    with boot(world, monkeypatch, retrieval=True, selective=True) as client:
        configure(client)
        assert "Tomas Weber" in ask(client, Q)["reply"]
    with boot(world, monkeypatch, retrieval=True, selective=False) as client:  # flag off: restart is the whole rollback
        configure(client)
        assert ask(client, Q)["reply"] == LLM_ANSWER and world.answer_calls == 1
    with boot(world, monkeypatch, retrieval=True, selective=True) as client:
        configure(client)
        assert "Tomas Weber" in ask(client, Q)["reply"]
        with psycopg.connect(world.dsn, autocommit=True) as conn:
            conn.execute("ALTER TABLE knowledge_items RENAME TO knowledge_items_offline")  # the index becomes unavailable mid-flight
        try:
            failed = ask(client, Q, "f1")
            assert failed["reply"] == sa.FAILURE_REPLY and world.answer_calls == 0
            assert LLM_ANSWER not in failed["reply"]
        finally:
            with psycopg.connect(world.dsn, autocommit=True) as conn:
                conn.execute("ALTER TABLE knowledge_items_offline RENAME TO knowledge_items")
        assert "Tomas Weber" in ask(client, Q, "f2")["reply"]  # recovered without a restart; the pool stayed healthy
        counts = client.app.state.selective_answerer.stats.counts
        assert sum(v for k, v in counts.items() if k.startswith("failed")) == 1 and backends(world) <= POOL_MAX
