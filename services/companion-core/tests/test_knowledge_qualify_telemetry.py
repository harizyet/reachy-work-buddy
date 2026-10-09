"""Phase 44E follow-up: knowledge-query qualification rules and the aggregate-only shadow telemetry. No model, no database."""

import json
import os
import stat
from datetime import UTC, datetime, timedelta

import pytest
from companion_core.knowledge.qualify import qualify, vocabulary_from_texts
from companion_core.knowledge.shadow_telemetry import (
    ALLOWED_FIELDS,
    FUNNEL,
    ShadowTelemetry,
    bucket,
    reconcile,
)

TERMS = frozenset({"harbor", "quill", "lantern", "falcon", "beacon", "priya", "tomas", "dana"})


@pytest.mark.parametrize("text", [
    "What are my open tasks?", "Who owns the Quill queue?", "What did we decide in the weekly sync?", "Which model is Harbor's default right now?",
    "Remind me what the Beacon support hours are", "List my completed tasks.", "Did Dana sign off the release?", "Show me my notes about Lantern.",
])
def test_knowledge_questions_qualify(text):
    assert qualify(text, known_terms=TERMS).qualifies


@pytest.mark.parametrize("text", [
    "Hello", "Thanks, that's all", "Tell me a joke", "What is the capital of France?", "Delete all my tasks", "Add a task to call the dentist",
    "Remind me to stretch in ten minutes", "/help", "What time is it?", "What's the weather like today?", "How do I boil an egg?", "Write a poem about robots",
    "Turn privacy mode on", "How many minutes are in a day?",
])
def test_chitchat_world_questions_and_actions_do_not_qualify(text):
    assert not qualify(text, known_terms=TERMS).qualifies


def test_a_reason_is_a_category_never_the_text():
    q = qualify("What are my open tasks about Quill?", known_terms=TERMS)
    assert q.reasons[0] == "question" and all(r in {"question", "first_person_or_team", "record_noun", "known_term"} for r in q.reasons)
    assert qualify("/help").reasons == ("command",) and qualify("Hello").reasons == ("smalltalk",)


def test_a_term_unknown_to_the_records_does_not_anchor_a_question():
    assert not qualify("Who painted the Mona Lisa?", known_terms=TERMS).qualifies
    assert qualify("How big is Quill?", known_terms=TERMS).qualifies and not qualify("How big is Quill?", known_terms=frozenset()).qualifies


def test_vocabulary_keeps_content_words_and_drops_short_and_stop_words():
    v = vocabulary_from_texts(["Harbor planning", "The Quill queue"], stop={"planning"})
    assert {"harbor", "quill", "queue"} <= v and "the" not in v and "planning" not in v


def clock(box):
    return lambda: box[0]


def test_the_funnel_reconciles_and_the_criterion_counts_only_evaluations(tmp_path):
    t = ShadowTelemetry(str(tmp_path / "t.jsonl"), flush_seconds=3600)
    for stage, n in (("attempted", 10), ("skipped_sensitive", 1), ("not_qualifying", 4), ("admitted", 5), ("dropped_busy", 1), ("failed_timeout", 1), ("failed_error", 0)):
        t.count(stage, n)
    t.job(path="retrieval", modality="text", intent=None, latency_ms=7, measured={"max_sensitivity": "work-private", "evidence_tokens": 300, "items_in_context": 4,
          "items_returned": 4, "revalidation_dropped": {"over_ceiling": 2}, "builder_dropped": {"duplicate": 1}})
    t.job(path="phase43", modality="text", intent=None, latency_ms=0.2, measured=None)
    t.job(path="status", modality="voice", intent="open_tasks", latency_ms=2, measured={"max_sensitivity": "public", "evidence_tokens": 90, "items_in_context": 0,
          "items_returned": 0, "revalidation_dropped": {}, "builder_dropped": {}})
    t.flush()
    totals = ShadowTelemetry.read_totals(str(tmp_path / "t.jsonl"))
    assert totals["counts"]["processed_ok"] == 3 and totals["evaluated_qualifying"] == 2  # the phase43 pass-through is processed but not an evaluation
    assert reconcile(totals["counts"]) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}
    assert reconcile({"attempted": 3, "admitted": 3, "processed_ok": 1}, pending=2) == {"attempted_unaccounted": 0, "admitted_unaccounted": 0}
    assert set(totals["counts"]) <= set(FUNNEL)


def test_rows_hold_aggregates_only_and_one_file_mode(tmp_path):
    path = tmp_path / "t.jsonl"
    t = ShadowTelemetry(str(path), flush_seconds=3600)
    t.count("attempted")
    t.count("admitted")
    t.job(path="retrieval", modality="text", intent=None, latency_ms=40, measured={"max_sensitivity": "work-private", "evidence_tokens": 800, "items_in_context": 3,
          "items_returned": 3, "revalidation_dropped": {}, "builder_dropped": {}})
    t.flush()
    (row,) = [json.loads(line) for line in path.read_text().splitlines()]
    assert set(row) <= ALLOWED_FIELDS and row["schema"] == 1 and row["latency_ms"] == {"25-50": 1} and row["evidence_tokens"] == {"500-1000": 1}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert bucket(0, (0, 250)) == "<=0" and bucket(9999, (5, 10)) == ">10"


def test_each_hour_is_its_own_window_and_retention_removes_old_rows_atomically(tmp_path):
    box = [datetime(2026, 1, 1, 10, 30, tzinfo=UTC)]
    path = tmp_path / "t.jsonl"
    t = ShadowTelemetry(str(path), retention_days=30, flush_seconds=3600, clock=clock(box))
    t.count("attempted")
    box[0] = datetime(2026, 1, 1, 11, 5, tzinfo=UTC)
    t.count("attempted")
    t.flush()
    assert [json.loads(line)["window_start"] for line in path.read_text().splitlines()] == ["2026-01-01T10:00Z", "2026-01-01T11:00Z"]
    box[0] = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=31)
    assert t.prune(force=True) == 2 and path.read_text() == "" and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    box[0] = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    t.count("attempted")
    t.flush()
    assert t.prune(force=True) == 0 and len(path.read_text().splitlines()) == 1  # recent rows survive; the clamp keeps retention between 1 and 365 days
    assert ShadowTelemetry(str(path), retention_days=0).retention_days == 1 and ShadowTelemetry(str(path), retention_days=9999).retention_days == 365


def test_a_telemetry_write_failure_is_counted_and_never_raised(tmp_path):
    t = ShadowTelemetry(str(tmp_path / "no-such-dir" / "t.jsonl"), flush_seconds=3600)
    t.count("attempted")
    t.flush()
    assert t.total["telemetry_write_failed"] == 1


def test_the_default_retention_is_thirty_days_and_the_environment_default_agrees(tmp_path, monkeypatch):
    from companion_core.knowledge.shadow import shadow_from_env

    assert ShadowTelemetry(str(tmp_path / "t.jsonl")).retention_days == 30
    monkeypatch.setenv("KNOWLEDGE_SHADOW_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_SHADOW_LOG_PATH", str(tmp_path / "s.jsonl"))
    monkeypatch.delenv("KNOWLEDGE_SHADOW_RETENTION_DAYS", raising=False)
    assert shadow_from_env(retriever=None, tasks=None, planner=None).telemetry.retention_days == 30
