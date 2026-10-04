"""Shadow router: validator behaviour, and the shadow contract driven through /conversation with mocked router and LLM transports.
The contract under test: production replies are identical with the shadow on or off, a failing shadow never reaches the turn,
and the records hold category-only reasons, no utterance text unless enabled, and the resolved target for forget/complete."""

import json
import os
import stat
import time

import httpx
import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.shadow_router import ShadowPipeline, shadow_from_env
from companion_core.shadow_router.validator import validate
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient

TURN = {"session_id": "s1", "conversation_id": "c1", "channel": "web"}


# ---- validator ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("route", "args", "text", "status"),
    [
        ("tasks.complete", {"task": "it"}, "mark it done", "needs_clarification"),
        ("tasks.complete", {"task": "that one"}, "that one's done", "needs_clarification"),
        ("tasks.complete", {"task": "call the plumber"}, "cross off call the plumber", "ok"),
        ("tasks.complete", {"task": "the dentist appointment"}, "mark it done", "needs_clarification"),  # invented target
        ("tasks.complete", {"task": "the slides or the budget"}, "mark the slides or the budget as done", "needs_clarification"),
        ("tasks.complete", {"task": "audit, tax tasks"}, "close both the audit and tax tasks", "needs_clarification"),
        ("memory.read", {"query": "what to look up/forget, copied/trimmed from the utterance; null if none is given"}, "what did I say", "needs_clarification"),
        ("memory.read", {"query": "null"}, "what do you remember", "needs_clarification"),
        ("memory.forget", {"query": "everything", "scope": "bulk"}, "forget all my notes", "bulk_refused"),
        ("memory.forget", {"query": "wifi code", "scope": "single"}, "forget everything about the wifi code", "bulk_refused"),  # words escalate
        ("memory.forget", {"query": "the key under the pot", "scope": "single"}, "remove the note about the key under the pot", "ok"),
        ("memory.capture", {"content": "this down"}, "note this down", "needs_clarification"),
        ("memory.capture", {"content": "the parking code is 4411"}, "note that the parking code is 4411", "ok"),
        ("tasks.capture", {"title": "add it to my list"}, "add it to my list", "needs_clarification"),
        ("tasks.capture", {"title": "ring the dentist", "due": "monday 9am"}, "add ring the dentist for monday", "ok"),
        ("email.draft", {"to": "him", "topic": "invoice"}, "email him about the invoice", "needs_clarification"),
        ("email.draft", {"to": "Priya", "topic": "the budget review"}, "draft an email to Priya about the budget review", "ok"),
    ],
)
def test_validator(route, args, text, status):
    assert validate(route, args, text).status == status


def test_validator_drops_an_ungrounded_optional_field_instead_of_executing_it():
    result = validate("tasks.capture", {"title": "ring the dentist", "due": "monday 9am"}, "add ring the dentist for monday")
    assert result.status == "ok"
    assert result.args["due"] is None
    assert "due:dropped_ungrounded:9am" in result.reasons


# ---- shadow contract through /conversation -------------------------------------------------------------------------------------

def _llm(extraction: dict | None, calls: list):
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "You extract arguments" in body["messages"][0]["content"]:
            if extraction is None:
                return httpx.Response(500)
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(extraction)}}]})
        if "classifier" in body["messages"][0]["content"].lower() and "speech_act" in body["messages"][0]["content"]:
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"intent": "none", "speech_act": "other", "confidence": 0.1})}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "A normal answer."}}]})
    return httpx.MockTransport(respond)


def _router(route: str | None):
    def respond(request: httpx.Request) -> httpx.Response:
        if route is None:
            return httpx.Response(503)
        return httpx.Response(200, json={"route": route, "confidence": 0.99, "member_routes": [route] * 3, "top3": [], "latency_ms": 5.0})
    return httpx.MockTransport(respond)


def _app(tmp_path, *, route, extraction=None, log_text=False, enabled=True):
    calls: list = []
    log = tmp_path / "shadow.jsonl"
    llm = _llm(extraction, calls)
    shadow = ShadowPipeline("http://router:8011", str(log), log_text=log_text, router_transport=_router(route), llm_transport=llm) if enabled else None
    app = create_app(
        calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(), run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        llm_transport=llm, shadow_router=shadow,
    )
    return app, shadow, log, calls


def _records(log, expected: int = 1):
    deadline = time.time() + 5
    while time.time() < deadline:
        if log.exists() and len(log.read_text().splitlines()) >= expected:
            break
        time.sleep(0.05)
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _configure(client):
    client.put("/settings/llm", json={"local": {"base_url": "http://ovms/v1", "model": "qwen"}})


def test_shadow_is_off_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("SHADOW_ROUTER_ENABLED", raising=False)
    assert shadow_from_env() is None
    monkeypatch.setenv("SHADOW_ROUTER_ENABLED", "true")
    monkeypatch.delenv("SHADOW_ROUTER_URL", raising=False)
    assert shadow_from_env() is None  # enabled but not configured: stays off


def test_production_reply_is_identical_with_the_shadow_on_and_off(tmp_path):
    text = "mark the roof inspection as complete"
    replies = []
    for enabled in (False, True):
        app, _shadow, _log, _calls = _app(tmp_path, route="tasks.complete", extraction={"task": "the roof inspection"}, enabled=enabled)
        with TestClient(app) as client:
            _configure(client)
            replies.append(client.post("/conversation", json={**TURN, "text": text}).json())
    assert replies[0] == replies[1]


def test_forget_records_the_resolved_target_and_no_text_by_default(tmp_path):
    app, shadow, log, _calls = _app(tmp_path, route="memory.forget", extraction={"query": "the garage code", "scope": "single"})
    with TestClient(app) as client:
        _configure(client)
        client.post("/conversation", json={**TURN, "text": "lose the note about the garage code"})
        (row,) = _records(log)
    assert row["router"]["route"] == "memory.forget"
    assert row["validator"]["status"] == "ok"
    assert row["proposed_action"] == "consent_gate:memory.forget"
    assert row["resolved_target"] == "the garage code"
    assert "text" not in row and "garage" not in json.dumps({k: v for k, v in row.items() if k != "resolved_target"})
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
    assert shadow.counters["would_execute_write"] == 1


def test_needs_clarification_records_a_reason_category_only(tmp_path):
    app, shadow, log, _calls = _app(tmp_path, route="tasks.complete", extraction={"task": "the dentist appointment"})
    with TestClient(app) as client:
        _configure(client)
        client.post("/conversation", json={**TURN, "text": "that one is wrapped up now"})
        (row,) = _records(log)
    assert row["validator"]["status"] == "needs_clarification"
    assert row["validator"]["reasons"] == ["task:ungrounded"]  # the invented words are not recorded
    assert row["proposed_action"] == "ask_clarification:task:ungrounded"
    assert row["resolved_target"] is None
    assert shadow.counters["withheld"] == 1


def test_text_is_logged_only_when_enabled_and_never_for_a_sensitive_turn(tmp_path):
    app, _shadow, log, _calls = _app(tmp_path, route="memory.capture", extraction={"content": "my salary is 90k"}, log_text=True)
    with TestClient(app) as client:
        _configure(client)
        client.post("/conversation", json={**TURN, "text": "remember my salary is 90k"})  # classify_privacy -> sensitive
        client.post("/conversation", json={**TURN, "text": "remember my locker number is 214"})
        rows = _records(log, 2)
    by_len = {r["text_len"]: r for r in rows}
    sensitive = by_len[len("remember my salary is 90k")]
    assert sensitive["privacy"] == "sensitive" and "text" not in sensitive
    assert by_len[len("remember my locker number is 214")]["text"] == "remember my locker number is 214"


def test_robot_routes_are_not_extracted_and_stay_on_the_production_classifier(tmp_path):
    app, _shadow, log, calls = _app(tmp_path, route="robot.standby", extraction={"x": 1})
    with TestClient(app) as client:
        _configure(client)
        client.post("/conversation", json={**TURN, "text": "could you put Reachy to sleep for a bit"})
        (row,) = _records(log)
    assert row["extraction"]["status"] == "skipped"
    assert row["proposed_action"] == "robot_suggestion_via_production_classifier"
    assert not any("You extract arguments" in c["messages"][0]["content"] for c in calls)


def test_shadow_failures_never_reach_the_production_turn(tmp_path):
    for route, extraction in ((None, None), ("tasks.complete", None)):  # router down; extractor 500
        app, shadow, _log, _calls = _app(tmp_path, route=route, extraction=extraction)
        with TestClient(app) as client:
            _configure(client)
            resp = client.post("/conversation", json={**TURN, "text": "mark the roof inspection as complete"})
            assert resp.status_code == 200
            deadline = time.time() + 5
            while time.time() < deadline and not (shadow.counters["router_error"] or shadow.counters["extractor_error"]):
                time.sleep(0.05)
        assert shadow.counters["router_error"] + shadow.counters["extractor_error"] == 1


def test_slash_commands_are_not_shadowed(tmp_path):
    app, shadow, log, _calls = _app(tmp_path, route="memory.forget", extraction={"query": "x", "scope": "single"})
    with TestClient(app) as client:
        _configure(client)
        client.post("/conversation", json={**TURN, "text": "/help"})
        time.sleep(0.3)
    assert not log.exists() and shadow.counters["turns"] == 0


# ---- bounded queue, trial cap, grading fields ----------------------------------------------------------------------------------

def _direct(tmp_path, **kwargs):
    from companion_core.shadow_router.shadow import ShadowTurn

    from shared.models.llm import LLMConfig, ProviderConfig

    calls: list = []
    log = tmp_path / "direct.jsonl"
    pipeline = ShadowPipeline("http://router:8011", str(log), router_transport=_router("tasks.complete"),
                              llm_transport=_llm({"task": "the roof inspection"}, calls), **kwargs)
    llm = LLMConfig(local=ProviderConfig(base_url="http://ovms/v1", model="qwen"))

    def turn(i: int):
        return ShadowTurn(session_id="s", text=f"mark the roof inspection as complete {i}", channel="web", modality="text",
                          privacy="public", production_handler="generic_chat", llm=llm)
    return pipeline, log, turn


def test_burst_drops_the_oldest_jobs_and_never_builds_a_backlog(tmp_path):
    import asyncio

    pipeline, log, turn = _direct(tmp_path, queue_size=3, log_text=True)

    async def go():
        for i in range(6):
            pipeline.submit(turn(i))  # all six arrive before the worker gets a turn
        await pipeline.drain()

    asyncio.run(go())
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert pipeline.counters["dropped_busy"] == 3
    assert [r["text"][-1] for r in rows] == ["3", "4", "5"]  # the newest three survive


def test_trial_cap_stops_recording(tmp_path):
    import asyncio

    pipeline, log, turn = _direct(tmp_path, queue_size=10, max_turns=2)

    async def go():
        for i in range(5):
            pipeline.submit(turn(i))
        await pipeline.drain()

    asyncio.run(go())
    assert len(log.read_text().splitlines()) == 2
    assert pipeline.counters["trial_complete_skipped"] == 3


@pytest.mark.parametrize("log_text", [False, True])
def test_validated_args_are_recorded_only_with_text_logging(tmp_path, log_text):
    import asyncio

    pipeline, log, turn = _direct(tmp_path, log_text=log_text)

    async def go():
        pipeline.submit(turn(1))
        await pipeline.drain()

    asyncio.run(go())
    (row,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert ("validated_args" in row) is log_text
    assert ("text" in row) is log_text


def test_turn_cap_counts_accepted_inputs_not_completed_records(tmp_path):
    import asyncio

    pipeline, log, turn = _direct(tmp_path, queue_size=1, max_turns=3)

    async def go():
        for i in range(5):
            pipeline.submit(turn(i))
        await pipeline.drain()

    asyncio.run(go())
    assert pipeline.counters["dropped_busy"] == 2  # accepted but displaced, so the trial does not stretch under contention
    assert pipeline.counters["trial_complete_skipped"] == 2
    assert len(log.read_text().splitlines()) == 1
