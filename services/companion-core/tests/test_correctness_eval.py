"""The Phase 24e correctness harness itself: case-file shape, scoring rules
and search detection through an in-process core. The model here is a fake,
so these tests say nothing about answer quality."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

EVAL_DIR = Path(__file__).parents[1] / "eval"
_spec = importlib.util.spec_from_file_location("run_correctness", EVAL_DIR / "run_correctness.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)


def test_case_file_is_well_formed():
    cases = json.loads((EVAL_DIR / "correctness-v1.json").read_text())
    assert cases["version"] == 1
    ids = [c["id"] for c in cases["conversations"]]
    assert len(ids) == len(set(ids))
    categories = set()
    for conversation in cases["conversations"]:
        for turn in conversation["turns"]:
            categories.add(turn["category"])
            assert set(turn["expect"]) <= {
                "search", "query_contains", "contains_all", "contains_any", "excludes", "max_words",
            }
            assert ("search_results" in turn or bool(turn.get("search_error"))) == turn["expect"]["search"]
    assert categories == {"context", "statement", "social", "self_identity", "search"}


@pytest.mark.parametrize(("expect", "reply", "failures"), [
    ({"contains_all": ["pineapple"]}, "Your code word was Pineapple.", []),
    ({"contains_all": ["pineapple"]}, "I don't remember.", ["missing 'pineapple'"]),
    ({"contains_any": ["five", "5", ["three", "two"]]}, "Three red and two blue.", []),
    ({"contains_any": ["five", "5"]}, "About 25 of them.", ["missing any of 'five', '5'"]),
    ({"contains_any": ["sun"]}, "Mostly sunny tomorrow.", []),
    ({"contains_any": ["couldn't"]}, "I couldn’t find that.", []),
    ({"excludes": ["0.1"]}, "Zig 0.13 is out.", ["contains '0.1'"]),
    ({"max_words": 3}, "one two three four", ["4 words > 3"]),
    ({}, "```python\nprint(1)\n```", ["code block"]),
])
def test_scoring_rules(expect, reply, failures):
    assert harness.score_turn(expect, reply, searched=False, query=None) == failures


def test_search_expectations_score_the_query():
    expect = {"search": True, "query_contains": ["singapore"]}
    assert harness.score_turn(expect, "ok", searched=True, query="weather in Singapore") == []
    assert harness.score_turn(expect, "ok", searched=False, query=None) == [
        "did not search", "query lacks 'singapore'",
    ]
    assert harness.score_turn({"search": False}, "ok", searched=True, query="q") == ["searched"]


def test_harness_runs_a_conversation_through_core():
    """A fake model that answers from the last user turn and any grounding
    it was given, so passes and failures come from core's real routing."""
    seen = []

    def fake_model(request):
        messages = json.loads(request.content)["messages"]
        seen.append(messages)
        grounding = " ".join(m["content"] for m in messages if "31°C" in m["content"])
        answer = "Thunderstorms, high 31." if grounding else "Noted."
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    cases = {
        "version": 0,
        "persona": {"name": "Reachy", "location": "Singapore", "timezone": "Asia/Singapore"},
        "conversations": [{"id": "weather", "turns": [
            {"text": "What's the weather today?", "category": "search",
             "search_results": [{"title": "Today", "url": "https://w.example/t", "content": "Thunderstorms, high 31°C."}],
             "expect": {"search": True, "query_contains": ["singapore"], "contains_all": ["31"]}},
            {"text": "Goodbye for now.", "category": "social", "expect": {"search": False, "max_words": 25}},
        ]}],
    }
    search = harness.FixtureSearch()
    with TestClient(harness.build_app(search, llm_transport=httpx.MockTransport(fake_model))) as client:
        harness.configure(client, cases, base_url="http://model.test/v1", model="fake", api_key=None, role="local")
        records = harness.run(client, cases, search, repeats=1)

    assert [r["failures"] for r in records] == [[], []]
    assert records[0]["searched"] and "Singapore" in records[0]["query"]
    assert not records[1]["searched"]
    summary = harness.summarize(records)
    assert summary["overall"] == {"passed": 2, "total": 2, "rate": 1.0}
    assert set(summary["categories"]) == {"search", "social"}
