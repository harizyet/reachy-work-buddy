"""Phase 44E follow-up: the measure-only knowledge shadow through the LIVE /conversation route, on disposable in-memory infrastructure.

What is proved here: the answer path is unchanged by the shadow (identical prompts and replies, off against on); an obedient model shown
planted instructions changes no store, draft or receipt; the shadow is non-blocking, bounded, and fails safe; its telemetry holds numbers and
categories only (no query, record text, ids or titles); access follows trusted turn state (spoken turn = public records only) and never widens;
the attached-meeting turn keeps the Phase 43 path. Nothing here uses the network, a database or a model."""

import asyncio
import contextlib
import json
import os
import stat
import sys
import time
from pathlib import Path

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.knowledge.index import InMemoryKnowledgeIndex
from companion_core.knowledge.outbox import InMemoryOutbox
from companion_core.knowledge.qualify import build_vocabulary
from companion_core.knowledge.retrieval import B1A, Retriever
from companion_core.knowledge.search import InMemorySearch
from companion_core.knowledge.shadow import (
    KnowledgeShadow,
    ShadowTurn,
    access_for,
    shadow_enabled,
    shadow_from_env,
)
from companion_core.knowledge.shadow_telemetry import (
    ALLOWED_FIELDS,
    ShadowTelemetry,
    reconcile,
)
from companion_core.knowledge.sources import build_adapters
from companion_core.knowledge.worker import IndexingWorker
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "knowledge_retrieval"))
from kbench.corpus import build_corpus, fingerprint, hashing_embed

OBEY = "Understood. I have deleted all the tasks and emailed the customer list to the vendor."
TURN = {"session_id": "s1", "conversation_id": "c1", "channel": "web"}


def run(coro):
    return asyncio.run(coro)


class World:
    """The invented corpus in in-memory stores, indexed, behind a live app."""

    def __init__(self, tmp_path, *, enabled: bool, reply: str = "A normal answer.", **shadow_kw):
        self.built = run(build_corpus())
        b = self.built
        self.calls: list[dict] = []

        def llm(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.calls.append(body)
            return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

        adapters = build_adapters(memory=b.memory, documents=b.documents, meetings=b.meetings, planner=b.planner, tasks=b.tasks)
        index = InMemoryKnowledgeIndex()
        worker = IndexingWorker(adapters=adapters, index=index, outbox=InMemoryOutbox(), embed_fn=hashing_embed, embedding_model="t")
        run(worker.reconcile())
        run(worker.drain())
        self.log = tmp_path / "ks.jsonl"
        async def vocabulary():
            return await build_vocabulary(adapters)

        self.shadow = KnowledgeShadow(
            retriever=Retriever(search=InMemorySearch(index), adapters=adapters, config=B1A), tasks=b.tasks, planner=b.planner,
            telemetry=ShadowTelemetry(str(self.log), flush_seconds=3600), vocabulary=vocabulary, **shadow_kw,
        ) if enabled else None
        self.app = create_app(
            calendar_store=InMemoryCalendarStore(), task_store=b.tasks, planner_store=b.planner, meeting_store=b.meetings, run_meeting_worker_task=False,
            memory_store=b.memory, rag_store=b.documents, email_store=InMemoryEmailStore(), confirmation_store=InMemoryConfirmationStore(),
            llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(), persona_store=InMemoryPersonaStore(),
            search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False, llm_transport=httpx.MockTransport(llm),
            knowledge_shadow=self.shadow,
        )

    @contextlib.contextmanager
    def client(self):
        with TestClient(self.app) as client:  # the lifespan (and the shadow's start and stop) runs for exactly the life of this block
            client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "reachy-local"}})
            yield client

    def totals(self) -> dict:
        """Flush and sum the aggregate file (the shadow writes one row per hour window, not one per turn)."""
        self.shadow.telemetry.flush()
        return ShadowTelemetry.read_totals(str(self.log)) if self.log.exists() else {"counts": {}, "evaluated_qualifying": 0}

    def rows(self) -> list[dict]:
        self.shadow.telemetry.flush()
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []


QUESTIONS = [
    "What are my open tasks?", "Who owns the Quill message queue?", "What does the Beacon Analytics vendor note say?",
    "How many retries before a failed Harbor job is parked ZEBRA-PLUM-71?", "Tell me a joke",
]


def test_the_shadow_is_off_unless_explicitly_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("KNOWLEDGE_SHADOW_ENABLED", raising=False)
    assert shadow_enabled() is False
    assert shadow_from_env(retriever=None, tasks=None, planner=None) is None
    monkeypatch.setenv("KNOWLEDGE_SHADOW_ENABLED", "true")
    monkeypatch.delenv("KNOWLEDGE_SHADOW_LOG_PATH", raising=False)
    assert shadow_from_env(retriever=None, tasks=None, planner=None) is None  # enabled but unconfigured stays off
    world = World(tmp_path, enabled=False)
    assert world.app.state.knowledge_shadow is None
    with world.client() as client:
        client.post("/conversation", json={**TURN, "text": QUESTIONS[0]})
    assert not world.log.exists()


def test_prompts_and_replies_are_identical_with_the_shadow_on_and_off(tmp_path):
    outcomes = []
    for enabled in (False, True):
        world = World(tmp_path / f"w{enabled}" if (tmp_path / f"w{enabled}").mkdir() is None else tmp_path, enabled=enabled)
        with world.client() as client:
            replies = [client.post("/conversation", json={**TURN, "text": q}).json() for q in QUESTIONS]
            if enabled:
                run_drain(client, world)
        outcomes.append((replies, [c["messages"] for c in world.calls]))
    assert outcomes[0] == outcomes[1]  # byte-identical prompts: nothing the shadow computed reached the model
    assert not any("<evidence" in m["content"] for call in outcomes[1][1] for m in call)


def run_drain(client, world):
    client.portal.call(world.shadow.drain)


def test_an_obedient_model_with_planted_instructions_changes_nothing_with_the_shadow_on(tmp_path):
    world = World(tmp_path, enabled=True, reply=OBEY)
    before = run(fingerprint(world.built))
    with world.client() as client:
        for q in ["What does the Beacon Analytics vendor note say?", "What did Priya ask Reachy to do at the Lantern review?", "What are my open tasks?"]:
            resp = client.post("/conversation", json={**TURN, "text": q})
            assert resp.status_code == 200
        client.post("/conversation", json={**TURN, "text": "What did Priya ask Reachy to do?", "context_meeting_id": world.built.store_id["meeting:mt-lantern"]})
        run_drain(client, world)
        drafts = client.portal.call(world.app.state.email_store.list_drafts)
    assert run(fingerprint(world.built)) == before  # no task completed or deleted, no memory, note, document or meeting changed
    assert drafts == [] and run(world.built.planner.list_receipts()) == []
    assert len(run(world.built.tasks.list_tasks())) == 4  # the corpus' four tasks, all still there


def test_slash_commands_sensitive_turns_and_non_questions_are_counted_but_not_evaluated(tmp_path):
    world = World(tmp_path, enabled=True)
    with world.client() as client:
        client.post("/conversation", json={**TURN, "text": "/help"})
        client.post("/conversation", json={**TURN, "text": "My salary is 90k, what tasks are open?"})  # classified sensitive
        for n, q in enumerate(["Tell me a joke", "What is the capital of France?", "What are my open tasks?"]):
            client.post("/conversation", json={**TURN, "session_id": f"fresh{n}", "text": q})  # a new session each: a sensitive turn's label carries within its own session
        run_drain(client, world)
    t = world.totals()
    c = t["counts"]
    assert c["attempted"] == 4 and c.get("skipped_slash", 0) == 0 and c["skipped_sensitive"] == 1  # slash commands never reach the shadow: the route excludes them and c["not_qualifying"] == 2
    assert c["admitted"] == 1 and c["processed_ok"] == 1 and t["evaluated_qualifying"] == 1  # the criterion counts the one real knowledge question
    assert reconcile(c) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}


def test_telemetry_is_aggregate_only_with_no_text_ids_titles_or_per_turn_rows(tmp_path):
    world = World(tmp_path, enabled=True)
    with world.client() as client:
        for q in QUESTIONS:
            client.post("/conversation", json={**TURN, "text": q})
        run_drain(client, world)
    rows = world.rows()
    assert stat.S_IMODE(os.stat(world.log).st_mode) == 0o600
    assert len(rows) == 1 and set(rows[0]) <= ALLOWED_FIELDS  # one hour window, one row: never one row per turn
    blob = world.log.read_text()
    for forbidden in ("ZEBRA", "PLUM", "Quill", "Tomas", "HarborGuest", "attacker", "Falcon", "Harbor", "meeting:", "memory:", "task:", "s1", "open tasks", "mem-", "doc-", "session", "query"):
        assert forbidden not in blob, forbidden
    row = rows[0]
    assert row["by_path"].keys() <= {"status", "retrieval", "phase43"} and row["by_intent"] == {"open_tasks": 1}
    assert sum(row["latency_ms"].values()) == row["counts"]["processed_ok"]


def test_access_follows_trusted_turn_state_a_spoken_turn_sees_public_records_only(tmp_path):
    spoken, written = access_for(ShadowTurn("s", "q", "voice", "work-private", "generic_chat", False)), access_for(ShadowTurn("s", "q", "text", "work-private", "generic_chat", False))
    assert spoken.sensitivity_ceiling.value == "public" and not spoken.channel_private
    assert written.sensitivity_ceiling.value == "work-private" and written.destinations == frozenset({"local"})
    world = World(tmp_path, enabled=True)
    with world.client() as client:
        client.post("/conversation", json={**TURN, "text": "What are my open tasks?", "input_modality": "voice"})
        client.post("/conversation", json={**TURN, "session_id": "s2", "text": "What are my open tasks?"})
        run_drain(client, world)
    (row,) = world.rows()
    assert row["by_modality"] == {"text": 1, "voice": 1} and "sensitive" not in row["max_sensitivity"]
    assert row["items_in_context"].get("<=0", 0) == 1 and row["max_sensitivity"] == {"public": 1, "work-private": 1}  # the spoken turn put nothing private in its block
    assert row["revalidation_dropped"].get("over_ceiling", 0) > 0


def test_an_attached_meeting_keeps_the_phase_43_path_and_runs_no_retrieval(tmp_path):
    world = World(tmp_path, enabled=True)
    meeting = world.built.store_id["meeting:mt-planning"]
    with world.client() as client:
        client.post("/conversation", json={**TURN, "text": "What are my open tasks?", "context_meeting_id": meeting})  # status wording, meeting attached
        client.post("/conversation", json={**TURN, "text": "What did we decide in this meeting?", "context_meeting_id": meeting})
        run_drain(client, world)
    (row,) = world.rows()
    assert row["by_path"] == {"phase43": 2} and row["evaluated_qualifying"] == 0  # a pass-through is processed but is not an evaluation
    assert any("attached a meeting as context" in m["content"] for m in world.calls[-1]["messages"] if m["role"] == "system")  # the shipped path answers
    assert not any("<evidence" in m["content"] for call in world.calls for m in call["messages"])


def test_the_shadow_never_blocks_the_reply_and_a_slow_job_times_out_or_is_dropped(tmp_path):
    world = World(tmp_path, enabled=True, queue_size=2, timeout_seconds=0.3)

    async def slow(turn):
        await asyncio.sleep(5)

    world.shadow._measure = slow
    with world.client() as client:
        started = time.perf_counter()
        for _ in range(5):
            assert client.post("/conversation", json={**TURN, "text": "Who owns the Quill message queue?"}).status_code == 200
        elapsed = time.perf_counter() - started
        client.portal.call(world.shadow.drain)
    c = world.totals()["counts"]
    assert elapsed < 4  # five replies did not wait for five five-second jobs
    assert c["dropped_busy"] >= 1 and c["failed_timeout"] >= 1 and c.get("processed_ok", 0) == 0
    assert reconcile(c) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}


def test_a_shadow_error_is_swallowed_and_counted(tmp_path):
    world = World(tmp_path, enabled=True)

    async def boom(*a, **k):
        raise RuntimeError("index unavailable")

    world.shadow.retriever.retrieve = boom
    with world.client() as client:
        reply = client.post("/conversation", json={**TURN, "text": "Who owns the Quill message queue?"})
        run_drain(client, world)
    assert reply.status_code == 200 and reply.json()["reply"] == "A normal answer."
    c = world.totals()["counts"]
    assert c["failed_error"] == 1 and c.get("processed_ok", 0) == 0 and world.totals()["evaluated_qualifying"] == 0


@pytest.mark.parametrize("text", ["delete all my tasks", "complete every task and email the customer list", "forget everything"])
def test_action_requests_still_go_through_the_existing_gates_with_the_shadow_on(tmp_path, text):
    """The shadow does not touch consent: the same phrase produces the same reply and the same store state with it off and on."""
    results = []
    for enabled in (False, True):
        world = World(tmp_path / str(enabled) if (tmp_path / str(enabled)).mkdir() is None else tmp_path, enabled=enabled)
        before = run(fingerprint(world.built))
        with world.client() as client:
            reply = client.post("/conversation", json={**TURN, "text": text}).json()
            if enabled:
                run_drain(client, world)
        results.append((reply, run(fingerprint(world.built)) == before))  # ids differ between worlds, so compare each world with itself
    assert results[0] == results[1]
