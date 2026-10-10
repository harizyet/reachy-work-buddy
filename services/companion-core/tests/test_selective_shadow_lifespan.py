"""Phase 44E selective shadow under the PRODUCTION lifespan on a disposable Postgres (DATABASE_MIGRATION_TEST_URL; synthetic data only): prerequisites, the one shared bounded pool, a foreground that
is identical (prompts, replies, model calls, authoritative data) with the shadow on and off, aggregate-only telemetry that never names a corpus record, restricted records and spoken turns, an index
fault isolated from the conversation and recovered without a restart, queue saturation with a reconciled funnel, and a clean shutdown. The model is a mock; nothing is deployed."""

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
from companion_core.knowledge import selective_shadow as ss
from fastapi.testclient import TestClient

from shared.protocols.accounts import SERVICE_HEADER

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "knowledge_retrieval"))
from kbench.corpus import build_corpus
from kbench.pg_env import build_pg_corpus, hashing_embed_384

needs_db = pytest.mark.skipif(not os.environ.get("DATABASE_MIGRATION_TEST_URL"), reason="requires explicitly disposable Postgres with pgvector")
TURN = {"conversation_id": "c1", "channel": "web"}
POOL_MAX = 5
LLM = "ORDINARY-MODEL-REPLY"
QUESTIONS = ["Who owns the Quill message queue?", "How many retries before a failed Harbor job is parked?", "What does the Beacon Analytics vendor note say?", "Tell me a joke",
             "What are my open tasks?", "Who attended the Lantern review?"]


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
    for name in (sa.RETRIEVAL_FLAG, sa.SELECTIVE_FLAG, ss.SHADOW_FLAG, "KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH", "KNOWLEDGE_SELECTIVE_SHADOW_QUEUE", "KNOWLEDGE_SHADOW_ENABLED",
                 "KNOWLEDGE_INDEXING_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    box = type("W", (), {})()
    box.dsn, box.root, box.env, box.log, box.calls, box.answer_calls, box.spec = env.dsn, root, env, tmp_path / "sshadow.jsonl", [], 0, spec
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


def boot(world, monkeypatch, *, shadow=True, retrieval=True, path=True, selective=False):
    world.calls, world.answer_calls = [], 0

    def llm(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        world.calls.append(body)
        if any(m.get("content") == ACTION_BOUNDARY_INSTRUCTION for m in body["messages"]):
            world.answer_calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": LLM}}]})

    for name, value in ((ss.SHADOW_FLAG, shadow), (sa.RETRIEVAL_FLAG, retrieval), (sa.SELECTIVE_FLAG, selective)):
        (monkeypatch.setenv(name, "true") if value else monkeypatch.delenv(name, raising=False))
    (monkeypatch.setenv("KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH", str(world.log)) if path else monkeypatch.delenv("KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH", raising=False))
    app = create_app(database_url=world.dsn, run_meeting_worker_task=False, run_email_dispatch_task=False, llm_transport=httpx.MockTransport(llm))
    return TestClient(app, headers={SERVICE_HEADER: "t" * 32})


def ask(client, text, session, *, voice=False):
    body = {**TURN, "session_id": session, "text": text}
    if voice:
        body["input_modality"] = "voice"
    return client.post("/conversation", json=body).json()


def configure(client):
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})


def totals(world):
    return ss.SelectiveShadowTelemetry.read_totals(str(world.log)) if world.log.exists() else {}


@needs_db
def test_prerequisites_shared_pool_and_an_identical_foreground(world, monkeypatch):
    for kw in ({"shadow": False}, {"retrieval": False}, {"path": False}):
        with boot(world, monkeypatch, **kw) as client:
            assert client.app.state.selective_shadow is None
            configure(client)
            ask(client, QUESTIONS[0], "x")
    assert not world.log.exists()  # no file unless every prerequisite is present
    before, outcomes = fingerprint(world), []
    for shadow in (False, True):
        with boot(world, monkeypatch, shadow=shadow) as client:
            configure(client)
            if shadow:
                observer = client.app.state.selective_shadow
                assert isinstance(observer, ss.SelectiveShadow) and observer.answerer.retriever.search._pool is client.app.state.task_store._pool  # no pool of its own
                assert client.app.state.selective_answerer is None  # the live path stays off: the shadow does not need it
            replies = [ask(client, q, f"s{n}") for n, q in enumerate(QUESTIONS)] + [ask(client, QUESTIONS[0], "v", voice=True)]
            if shadow:
                client.portal.call(observer.drain)
                assert backends(world) <= POOL_MAX
            outcomes.append((replies, [c["messages"] for c in world.calls], world.answer_calls))
        assert backends(world) == 0  # shutdown released everything
    assert outcomes[0] == outcomes[1] and fingerprint(world) == before
    assert not any("<evidence" in m["content"] for call in outcomes[1][1] for m in call)
    t = totals(world)
    assert t["funnel"]["attempted"] == len(QUESTIONS) + 1 and ss.reconcile(t["funnel"]) == 0
    assert t["class"]["typed"] >= 2 and t["class"]["untyped"] >= 1 and t["class"]["ineligible"] >= 2
    assert t["record_dependent_untyped_by_path"].get("model", 0) >= 1 and sum(v for k, v in t["outcome"].items() if k.startswith("answered")) >= 2 and not [k for k in t["outcome"] if k.startswith("failed")]


@needs_db
def test_telemetry_never_names_a_corpus_record_and_restricted_data_is_never_counted_as_cited(world, monkeypatch):
    with boot(world, monkeypatch) as client:
        configure(client)
        observer = client.app.state.selective_shadow
        for n, q in enumerate(QUESTIONS * 2):
            ask(client, q, f"t{n}", voice=n % 2 == 1)
        client.portal.call(observer.drain)
    blob = world.log.read_text()
    words = set()
    for key in ("memories", "notes", "documents", "meetings"):
        for record in world.spec[key]:
            words |= {w for field in ("text", "body", "title", "content") if record.get(field) for w in str(record[field]).split() if len(w) > 5 and w.isalpha()}
    schema = {tok for name in [*ss.VOCABULARY, *(n for names in ss.VOCABULARY.values() for n in names), "schema", "window_start", "groups"] for tok in name.replace("-", "_").split("_")}
    import re

    leaked = sorted((words - schema) & set(re.findall(r"[A-Za-z0-9]+", blob)))  # whole tokens: "unsupported" is the schema's word, not a leak of "support"
    assert words and not leaked, f"corpus words in the telemetry: {leaked}"
    assert "sensitive" not in totals(world).get("max_sensitivity", {}) and set(totals(world)["max_sensitivity"]) <= {"none", "public", "work-private"}


@needs_db
def test_an_index_fault_is_isolated_from_the_conversation_and_recovers_without_a_restart(world, monkeypatch):
    with boot(world, monkeypatch) as client:
        configure(client)
        observer = client.app.state.selective_shadow
        baseline = ask(client, QUESTIONS[0], "a")
        with psycopg.connect(world.dsn, autocommit=True) as conn:
            conn.execute("ALTER TABLE knowledge_items RENAME TO knowledge_items_offline")
        try:
            faulted = ask(client, QUESTIONS[0], "b")
            client.portal.call(observer.drain)
        finally:
            with psycopg.connect(world.dsn, autocommit=True) as conn:
                conn.execute("ALTER TABLE knowledge_items_offline RENAME TO knowledge_items")
        recovered = ask(client, QUESTIONS[0], "c")
        client.portal.call(observer.drain)
        assert baseline["reply"] == faulted["reply"] == recovered["reply"] == LLM and backends(world) <= POOL_MAX
    t = totals(world)
    assert sum(v for k, v in t["outcome"].items() if k.startswith("failed")) >= 1 and t["outcome"]["answered_supported"] >= 2
    assert ss.reconcile(t["funnel"]) == 0


@needs_db
def test_queue_saturation_under_the_real_database_keeps_the_foreground_fast_and_the_funnel_reconciled(world, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_SELECTIVE_SHADOW_QUEUE", "2")
    with boot(world, monkeypatch) as client:
        configure(client)
        observer = client.app.state.selective_shadow
        real = observer.answerer.retriever

        class Delayed:  # the real database behind a slow retrieval, so a burst genuinely saturates the queue
            async def retrieve(self, *a, **k):
                await asyncio.sleep(0.2)
                return await real.retrieve(*a, **k)

        observer.answerer.retriever = Delayed()
        started = time.perf_counter()
        for n in range(40):
            assert ask(client, QUESTIONS[n % 3], f"q{n}")["reply"] == LLM
        elapsed = time.perf_counter() - started
        client.portal.call(observer.drain)
    f = totals(world)["funnel"]
    assert f["attempted"] == 40 and f["dropped_busy"] >= 10 and ss.reconcile(f) == 0 and f["processed_ok"] + f["dropped_busy"] == f["admitted"]
    assert elapsed < 60 and backends(world) == 0
    print(f"\n40 foreground turns with the shadow on: {elapsed:.1f} s, dropped {f.get('dropped_busy', 0)}, processed {f['processed_ok']}")
