"""Phase 44E selective shadow (D3, 2026-10-10) through the LIVE /conversation route, on disposable in-memory infrastructure.

Proved here: the shadow exists only with its flag AND retrieval AND a log path; the ordinary reply, prompts and model calls are identical with it on and off and it never releases a deterministic
answer; a slow or failing shadow never delays or changes a reply; routing classes (typed, ambiguous, untyped, ineligible) and outcomes are counted from a fixed vocabulary; the telemetry file holds
categories only (no question, reply, evidence, title, record id or session id can be written); a restricted record changes no counter and a spoken turn is assessed with public access only; queue
saturation drops the oldest and every admitted job is accounted for; stop and restart are clean. Real PostgreSQL is in test_selective_shadow_lifespan.py. No network, database or model is used here."""

import asyncio
import contextlib
import json
import logging
import stat
import sys
import time
from pathlib import Path

import httpx
import pytest
from companion_core.app import ACTION_BOUNDARY_INSTRUCTION, create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.knowledge import selective_answer as sa
from companion_core.knowledge import selective_shadow as ss
from companion_core.knowledge.index import InMemoryKnowledgeIndex
from companion_core.knowledge.outbox import InMemoryOutbox
from companion_core.knowledge.qualify import build_vocabulary
from companion_core.knowledge.retrieval import B1A, Retriever
from companion_core.knowledge.search import InMemorySearch
from companion_core.knowledge.sources import build_adapters
from companion_core.knowledge.worker import IndexingWorker
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

from shared.models.response import Privacy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "knowledge_retrieval"))
from kbench.corpus import build_corpus, fingerprint, hashing_embed

P, W, S = Privacy.PUBLIC, Privacy.WORK_PRIVATE, Privacy.SENSITIVE
LLM_ANSWER = "ORDINARY-MODEL-REPLY"
TURN = {"channel": "web", "conversation_id": "c1"}
FERRY = [("The owner of the Ferry queue is Dana Whitfield.", W)]
OWNER_Q = "Who owns the Ferry queue?"
QUILL_Q = "Who owns the Quill message queue?"


def run(coro):
    return asyncio.run(coro)


class Slow:
    def __init__(self, inner, how):
        self.inner, self.how = inner, how

    async def retrieve(self, *a, **k):
        if self.how == "raise":
            raise ConnectionError("db down: SECRET-HOST")
        if self.how == "slow":
            await asyncio.sleep(1.0)
        if self.how == "hang":
            await asyncio.sleep(30)
        return await self.inner.retrieve(*a, **k)


class World:
    def __init__(self, tmp_path, *, shadow=True, extra=(), wrap=None, index_count=None, queue_size=10, timeout=3.0, reply=LLM_ANSWER, live=False):
        self.built = b = run(build_corpus())
        for text, sensitivity in extra:
            run(b.memory.add_memory(content=text, source="conversation", sensitivity=sensitivity))
        self.answer_calls, self.model_calls = 0, []

        def llm(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.model_calls.append(body)
            if any(m.get("content") == ACTION_BOUNDARY_INSTRUCTION for m in body["messages"]):
                self.answer_calls += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

        adapters = build_adapters(memory=b.memory, documents=b.documents, meetings=b.meetings, planner=b.planner, tasks=b.tasks)
        self.index = InMemoryKnowledgeIndex()
        worker = IndexingWorker(adapters=adapters, index=self.index, outbox=InMemoryOutbox(), embed_fn=hashing_embed, embedding_model="t")
        run(worker.reconcile())
        run(worker.drain())
        retriever = Retriever(search=InMemorySearch(self.index), adapters=adapters, config=B1A)
        if wrap:
            retriever = wrap(retriever)
        self.log = tmp_path / "selective-shadow.jsonl"
        self.shadow = ss.SelectiveShadow(
            answerer=sa.SelectiveAnswerer(retriever=retriever, index_count=index_count or self.index.count, vocabulary=lambda: build_vocabulary(adapters), timeout_seconds=timeout),
            telemetry=ss.SelectiveShadowTelemetry(str(self.log), flush_seconds=3600), queue_size=queue_size, timeout_seconds=timeout) if shadow else None
        answerer = sa.SelectiveAnswerer(retriever=Retriever(search=InMemorySearch(self.index), adapters=adapters, config=B1A), index_count=self.index.count,
                                        vocabulary=lambda: build_vocabulary(adapters)) if live else None
        self.app = create_app(
            calendar_store=InMemoryCalendarStore(), task_store=b.tasks, planner_store=b.planner, meeting_store=b.meetings, run_meeting_worker_task=False,
            memory_store=b.memory, rag_store=b.documents, email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
            search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False, llm_transport=httpx.MockTransport(llm),
            selective_shadow_observer=self.shadow, selective_answerer=answerer,
        )

    @contextlib.contextmanager
    def client(self):
        with TestClient(self.app) as client:
            client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})
            yield client

    def ask(self, client, text, *, voice=False, session=None):
        body = {**TURN, "session_id": session or f"s{abs(hash(text)) % 10**6}", "text": text}
        if voice:
            body["input_modality"] = "voice"
        return client.post("/conversation", json=body).json()

    def drain(self, client):
        client.portal.call(self.shadow.drain)

    def totals(self):
        self.shadow.telemetry.flush()
        return ss.SelectiveShadowTelemetry.read_totals(str(self.log)) if self.log.exists() else {}


MIX = [QUILL_Q, "How many retries before a failed Harbor job is parked?", "Who attended the Lantern review?", "What does the Beacon Analytics vendor note say?", "Tell me a joke",
       "What are my open tasks?", "Who owns the Quill message queue and who runs the Harbor scheduler?", "Delete all my memories"]


# -- flags and prerequisites -------------------------------------------------------------------------------------------------------------

def test_the_shadow_exists_only_with_its_flag_retrieval_and_a_log_path(monkeypatch, tmp_path, caplog):
    for name in (ss.SHADOW_FLAG, sa.RETRIEVAL_FLAG, "KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH", sa.SELECTIVE_FLAG):
        monkeypatch.delenv(name, raising=False)
    kw = {"retriever": None, "index_count": None}
    assert ss.selective_shadow_enabled() is False and ss.from_env(**kw) is None
    monkeypatch.setenv(sa.RETRIEVAL_FLAG, "true")
    assert ss.from_env(**kw) is None  # retrieval alone
    monkeypatch.setenv(ss.SHADOW_FLAG, "true")
    monkeypatch.delenv(sa.RETRIEVAL_FLAG)
    with caplog.at_level(logging.WARNING, logger="companion_core.knowledge_selective_shadow"):
        assert ss.from_env(**kw) is None  # shadow without retrieval
        monkeypatch.setenv(sa.RETRIEVAL_FLAG, "true")
        assert ss.from_env(**kw) is None  # no log path
    assert caplog.text.count("stays off") == 2
    monkeypatch.setenv("KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH", str(tmp_path / "x.jsonl"))
    assert isinstance(ss.from_env(**kw), ss.SelectiveShadow)  # the live selective flag is not needed
    for off in ("false", "0", "", "maybe"):
        monkeypatch.setenv(ss.SHADOW_FLAG, off)
        assert ss.from_env(**kw) is None
    world = World(tmp_path, shadow=False)
    assert world.app.state.selective_shadow is None
    with world.client() as client:
        world.ask(client, QUILL_Q)
    assert not world.log.exists()


# -- the foreground is untouched ---------------------------------------------------------------------------------------------------------

def test_prompts_replies_and_model_calls_are_identical_with_the_shadow_on_and_off_and_nothing_is_released(tmp_path):
    outcomes = []
    for shadow in (False, True):
        (tmp_path / str(shadow)).mkdir()
        world = World(tmp_path / str(shadow), shadow=shadow)
        before = run(fingerprint(world.built))
        with world.client() as client:
            replies = [world.ask(client, q) for q in MIX]
            if shadow:
                world.drain(client)
        assert run(fingerprint(world.built)) == before  # no record changed
        outcomes.append((replies, [c["messages"] for c in world.model_calls], world.answer_calls))
    assert outcomes[0] == outcomes[1]
    assert all(r["reply"] == LLM_ANSWER or "I can't perform" in r["reply"] or "tasks" in r["reply"].lower() for r in outcomes[1][0])
    assert not any("<evidence" in m["content"] for call in outcomes[1][1] for m in call)  # the shadow's retrieval never enters a prompt
    assert outcomes[1][0][0]["reply"] == LLM_ANSWER  # the typed Quill question is answered by the ordinary path; the deterministic answer is never released


def test_a_slow_hanging_or_failing_shadow_never_delays_or_changes_a_reply(tmp_path):
    base = World(tmp_path / "a" if (tmp_path / "a").mkdir() is None else tmp_path, shadow=False)
    with base.client() as client:
        expected = base.ask(client, QUILL_Q)
    for n, how in enumerate(("slow", "hang", "raise")):
        (tmp_path / how).mkdir()
        world = World(tmp_path / how, wrap=lambda r, how=how: Slow(r, how), timeout=0.4)
        with world.client() as client:
            started = time.perf_counter()
            got = [world.ask(client, QUILL_Q, session=f"x{i}") for i in range(4)]
            elapsed = time.perf_counter() - started
            world.drain(client)
        assert all(g == expected for g in got) and elapsed < 5, how  # a 30 s hang or a 1 s retrieval in the shadow does not show in the foreground
        outcomes = world.totals().get("outcome", {})
        if how == "raise":
            assert outcomes.get("failed_retrieval", 0) >= 1
        if how == "hang":
            assert outcomes.get("failed_timeout", 0) >= 1 or world.totals()["funnel"].get("failed_timeout", 0) >= 1


# -- routing classes and outcomes ------------------------------------------------------------------------------------------------------

def test_routing_classes_outcomes_and_the_untyped_record_dependent_concern_are_counted(tmp_path):
    world = World(tmp_path, extra=FERRY)
    with world.client() as client:
        for q in [*MIX, OWNER_Q, "Who owns the Ferry queue and who runs the Harbor scheduler?"]:
            world.ask(client, q)
        world.drain(client)
    t = world.totals()
    assert t["funnel"]["attempted"] == len(MIX) + 2 and ss.reconcile(t["funnel"]) == 0
    assert t["class"]["typed"] >= 3 and t["class"]["ineligible"] >= 3 and t["class"]["untyped"] >= 2
    assert t["ineligible_reason"]["status_question"] >= 1 and t["ineligible_reason"]["not_knowledge"] >= 1
    assert t["untyped_reason"]["not_understood"] >= 1
    assert sum(t["untyped_anchor_strength"].values()) == t["class"]["untyped"]
    assert t["record_dependent_untyped_by_path"]["model"] >= 2  # untyped personal-knowledge questions answered by the ordinary model: the activation-safety measure
    assert t["production_path"]["model"] >= 4 and t["production_path"]["handler"] >= 1 and t["production_path"]["action_boundary"] == 1
    assert t["outcome"]["answered_supported"] >= 2 and sum(t["citations"].values()) == sum(t["outcome"].values())
    assert set(t["max_sensitivity"]) <= {"none", "public", "work-private"} and t["modality"]["text"] == len(MIX) + 2


# -- aggregate-only by construction ------------------------------------------------------------------------------------------------------

def test_the_telemetry_holds_categories_only_whatever_is_asked_or_stored(tmp_path):
    secret = [("The owner of the Ferry queue is Dana Whitfield. Credential hunter2-ZEBRA belongs to Priya Raman.", W)]
    world = World(tmp_path, extra=secret)
    questions = [OWNER_Q, "Who owns the Ferry queue and what is hunter2-ZEBRA?", "My password hunter2 is on what note?", "Who is Priya Raman?"]
    with world.client() as client:
        for i, q in enumerate(questions):
            world.ask(client, q, session=f"session-secret-{i}")
        world.drain(client)
    world.shadow.telemetry.flush()
    blob = world.log.read_text()
    for word in ("Ferry", "Dana", "Whitfield", "hunter2", "ZEBRA", "Priya", "session-secret", "memory:", "owns", "password", "note", "Quill"):
        assert word not in blob, word
    for line in blob.splitlines():
        row = json.loads(line)
        assert set(row) <= ss.ALLOWED_FIELDS
        for group, counts in row["groups"].items():
            assert group in ss.VOCABULARY
            for name, n in counts.items():
                assert isinstance(n, int) and (group == "latency_ms" or name in ss.VOCABULARY[group] or name == "other"), (group, name)
    assert stat.S_IMODE(world.log.stat().st_mode) == 0o600
    tel = ss.SelectiveShadowTelemetry(str(tmp_path / "t.jsonl"))
    tel.count("outcome", "Dana Whitfield said hunter2")
    tel.count("not_a_group", "x")
    tel.flush()
    assert (tmp_path / "t.jsonl").read_text().count("hunter2") == 0 and ss.SelectiveShadowTelemetry.read_totals(str(tmp_path / "t.jsonl")) == {"outcome": {"other": 1}}


# -- trust and restricted sources --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("voice", [False, True])
def test_a_restricted_record_changes_no_counter_and_a_spoken_turn_is_assessed_with_public_access_only(tmp_path, voice):
    restricted = [("The owner of the Ferry queue is Marcus Ode.", S), ("The owner of the Zephyr cache is Marcus Ode.", S)]
    totals = []
    for name, extra in (("with", [*FERRY, *restricted]), ("without", FERRY)):
        (tmp_path / name).mkdir()
        world = World(tmp_path / name, extra=extra)
        with world.client() as client:
            for q in (OWNER_Q, "Who owns the Zephyr cache?", QUILL_Q):
                world.ask(client, q, voice=voice)
            world.drain(client)
        totals.append(world.totals())
    stable = {g: totals[0][g] for g in ("class", "outcome", "citations", "max_sensitivity", "modality", "ineligible_reason", "untyped_reason", "anchor") if g in totals[0]}
    assert stable == {g: totals[1][g] for g in stable}, "the presence of a restricted record must not change any counter"
    if voice:
        assert set(totals[0]["max_sensitivity"]) <= {"none", "public"}  # a spoken turn never retrieves above public, even internally
    else:
        assert "sensitive" not in totals[0].get("max_sensitivity", {})


def test_a_spoken_turn_cannot_cite_a_work_private_record_even_in_the_shadow(tmp_path):
    world = World(tmp_path, extra=FERRY)
    with world.client() as client:
        world.ask(client, OWNER_Q, voice=True)
        world.ask(client, OWNER_Q, voice=False, session="t")
        world.drain(client)
    t = world.totals()
    assert t["max_sensitivity"].get("work-private") == 1 and t["max_sensitivity"].get("none") == 1  # the text turn cites it, the spoken one does not


# -- failures, saturation, lifecycle -----------------------------------------------------------------------------------------------------

def test_dependency_failures_are_bounded_categories_and_leak_nothing(tmp_path, caplog):
    cases = {"retrieval": {"wrap": lambda r: Slow(r, "raise")}, "not_ready": {"index_count": lambda: _zero()}, "timeout": {"wrap": lambda r: Slow(r, "hang"), "timeout": 0.3}}
    for kind, kw in cases.items():
        (tmp_path / kind).mkdir()
        world = World(tmp_path / kind, **kw)
        with caplog.at_level(logging.DEBUG), world.client() as client:
            assert world.ask(client, QUILL_Q)["reply"] == LLM_ANSWER
            world.drain(client)
        assert world.totals()["outcome"] == {f"failed_{kind}": 1}
        assert "SECRET-HOST" not in caplog.text and "Quill" not in caplog.text


async def _zero():
    return 0


def test_an_error_inside_the_job_is_counted_and_never_reaches_the_reply(tmp_path, monkeypatch):
    world = World(tmp_path)
    monkeypatch.setattr(world.shadow.answerer, "classify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with world.client() as client:
        assert world.ask(client, QUILL_Q)["reply"] == LLM_ANSWER
        world.drain(client)
    t = world.totals()["funnel"]
    assert t["failed_error"] == 1 and ss.reconcile(t) == 0


def test_queue_saturation_drops_the_oldest_never_slows_replies_and_every_job_is_accounted_for(tmp_path):
    world = World(tmp_path, wrap=lambda r: Slow(r, "slow"), queue_size=2, timeout=3.0)
    with world.client() as client:
        started = time.perf_counter()
        for i in range(10):
            world.ask(client, QUILL_Q, session=f"q{i}")
        assert time.perf_counter() - started < 5
        world.drain(client)
    f = world.totals()["funnel"]
    assert f["attempted"] == 10 and f["dropped_busy"] >= 5 and ss.reconcile(f) == 0
    assert f["processed_ok"] + f["dropped_busy"] == f["admitted"]


def test_stop_counts_what_was_queued_and_a_restart_continues_the_same_file(tmp_path):
    world = World(tmp_path, wrap=lambda r: Slow(r, "slow"), queue_size=10, timeout=3.0)
    with world.client() as client:
        for i in range(6):
            world.ask(client, QUILL_Q, session=f"q{i}")
    f = world.totals()["funnel"]  # leaving the client context stopped the shadow
    assert ss.reconcile(f) == 0 and f["attempted"] == 6
    second = World(tmp_path, wrap=None)
    with second.client() as client:
        second.ask(client, QUILL_Q, session="again")
        second.drain(client)
    again = second.totals()
    assert again["funnel"]["attempted"] == 7 and ss.reconcile(again["funnel"]) == 0  # rows appended to the same file; consumers sum them


def test_the_live_answerer_and_the_shadow_coexist_and_the_shadow_still_releases_nothing(tmp_path):
    world = World(tmp_path, extra=FERRY, live=True)
    with world.client() as client:
        got = world.ask(client, OWNER_Q)
        world.drain(client)
    assert got["reply"].startswith("The owner of the Ferry queue is Dana Whitfield [E1].")  # released by the live path only
    t = world.totals()
    assert t["production_path"] == {"selective": 1} and t["outcome"]["answered_supported"] == 1
    assert world.shadow.answerer.stats.counts == {}  # the shadow never touches the live counters


# -- follow-up: a shadow cannot create a partial foreground response or delay ordinary conversation ----------------------------------------------

def test_a_failing_or_crashing_submit_cannot_alter_or_truncate_the_reply(tmp_path, monkeypatch):
    base = World(tmp_path / "base" if (tmp_path / "base").mkdir() is None else tmp_path, shadow=False)
    with base.client() as client:
        expected = base.ask(client, QUILL_Q)
    world = World(tmp_path)
    monkeypatch.setattr(world.shadow, "submit", lambda turn: (_ for _ in ()).throw(RuntimeError("shadow exploded mid-submit")))
    with world.client() as client:
        got = world.ask(client, QUILL_Q)
        assert got == expected and got["reply"] == LLM_ANSWER and got["turn_count"] == expected["turn_count"]  # whole response, same status and body
        assert client.post("/conversation", json={**TURN, "session_id": "z", "text": QUILL_Q}).status_code == 200


def test_the_reply_is_decided_before_the_shadow_sees_the_turn_and_the_offer_is_constant_time(tmp_path):
    world = World(tmp_path)
    seen = []
    real = world.shadow.submit

    def spy(turn):
        seen.append(turn.privacy)  # the label of the finished reply; the shadow is offered a snapshot of plain data, not the response object
        real(turn)

    world.shadow.submit = spy
    with world.client() as client:
        got = world.ask(client, QUILL_Q)
        world.drain(client)
    assert got["reply"] == LLM_ANSWER and seen == [got["privacy"]]
    started = time.perf_counter()
    for i in range(500):
        world.shadow.submit(ss.SelectiveShadowTurn(f"s{i}", QUILL_Q, "text", "work-private", "generic_chat", False))
    assert (time.perf_counter() - started) / 500 < 0.005  # measured about 3 microseconds per offer; the bound is generous
    run(world.shadow.stop())


def test_shadow_work_never_stalls_the_event_loop_for_long():
    """Jobs run on the service's event loop. Measured with a 1 ms heartbeat while 120 offered jobs ran (typed, ambiguous, untyped and chat questions over 15 retrieved records): the
    longest gap was about 30 ms. The bound here is several times that, so only a real regression (an unbounded loop, a blocking call) trips it."""
    import tempfile

    world = World(Path(tempfile.mkdtemp()), extra=FERRY)
    questions = [QUILL_Q, OWNER_Q, "How many retries before a failed Harbor job is parked?", "Who owns the Quill message queue and who runs the Harbor scheduler?", "Who attended the Lantern review?", "Tell me a joke"]

    async def scenario():
        shadow = world.shadow
        await shadow.start()
        gaps, stop = [], False

        async def beat():
            last = time.perf_counter()
            while not stop:
                await asyncio.sleep(0.001)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        heartbeat = asyncio.create_task(beat())
        await asyncio.sleep(0.05)
        gaps.clear()
        for i in range(120):
            shadow.submit(ss.SelectiveShadowTurn(f"s{i}", questions[i % len(questions)], "text", "work-private", "generic_chat", False))
        await shadow.drain()
        stop = True
        await heartbeat
        await shadow.stop()
        return max(gaps)

    assert run(scenario()) < 0.25
