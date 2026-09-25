"""Phase 24e correctness set runner.

Runs each conversation in a correctness-vN.json file through an in-process
companion-core with in-memory stores, fixture search results and a real
OpenAI-compatible model, then scores every turn that has an `expect` block.
The scoring rules are in docs/phase-24e.md#correctness-set-scoring-rules;
this module is their only implementation. It measures, it does not judge:
compare the printed scores against the threshold the owner agreed first.

    uv run python services/companion-core/eval/run_correctness.py \
        --base-url http://localhost:8000/v3 --model <model> --out <dir>

Turns use the voice modality on the Reachy channel, like robot turns. No
hub, robot, database or real search provider is contacted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

DEFAULT_CASES = Path(__file__).with_name("correctness-v1.json")
# Environment that would point the in-process core at real services.
_SCRUBBED_ENV = ("DATABASE_URL", "ACCOUNTS_SERVICE_TOKEN", "REACHY_HUB_URL", "REMOTE_UI_TOKEN")


def _normalize_reply(reply: str) -> str:
    return reply.lower().replace("’", "'").replace("‘", "'")


def _has_term(reply: str, term: str) -> bool:
    # Left word boundary only: "sun" matches "sunny", "5" does not match "25".
    return re.search(r"(?<!\w)" + re.escape(term.lower()), reply) is not None


def _has_alternative(reply: str, alternative: str | list[str]) -> bool:
    if isinstance(alternative, list):
        return all(_has_term(reply, term) for term in alternative)
    return _has_term(reply, alternative)


def score_turn(expect: dict, reply: str, *, searched: bool, query: str | None) -> list[str]:
    """Failed checks for one turn; empty means the turn passes."""
    failures = []
    text = _normalize_reply(reply)
    if "```" in reply:
        failures.append("code block")
    if "search" in expect and searched != expect["search"]:
        failures.append("searched" if searched else "did not search")
    for term in expect.get("query_contains", []):
        if query is None or term.lower() not in query.lower():
            failures.append(f"query lacks {term!r}")
    for alternative in expect.get("contains_all", []):
        if not _has_alternative(text, alternative):
            failures.append(f"missing {alternative!r}")
    if expect.get("contains_any") and not any(_has_alternative(text, a) for a in expect["contains_any"]):
        failures.append("missing any of " + ", ".join(repr(a) for a in expect["contains_any"]))
    for term in expect.get("excludes", []):
        if _has_term(text, term):
            failures.append(f"contains {term!r}")
    words = len(reply.split())
    if "max_words" in expect and words > expect["max_words"]:
        failures.append(f"{words} words > {expect['max_words']}")
    return failures


class FixtureSearch:
    """SearXNG-shaped responses for the turn being run."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.error = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.error:
            return httpx.Response(503)
        return httpx.Response(200, json={"results": self.results})


def build_app(search: FixtureSearch, *, llm_transport: httpx.AsyncBaseTransport | None = None):
    from companion_core.app import create_app
    from companion_core.calendar.store import InMemoryCalendarStore
    from companion_core.consent.store import InMemoryConfirmationStore
    from companion_core.email.store import InMemoryEmailStore
    from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
    from companion_core.memory.store import InMemoryMemoryStore
    from companion_core.persona.store import InMemoryPersonaStore
    from companion_core.rag.store import InMemoryDocumentStore
    from companion_core.tasks.store import InMemoryTaskStore
    from companion_core.websearch.store import InMemorySearchSettingsStore

    for name in _SCRUBBED_ENV:
        os.environ.pop(name, None)
    return create_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        llm_transport=llm_transport,
        websearch_transport=httpx.MockTransport(search.handle),
        # Anything core sends to the hub fails closed instead of leaving the host.
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
        run_email_dispatch_task=False,
    )


def configure(client, cases: dict, *, base_url: str, model: str, api_key: str | None, role: str) -> None:
    provider = {"base_url": base_url, "model": model, **({"api_key": api_key} if api_key else {})}
    mode = "local_only" if role == "local" else "cloud_only"
    client.put("/settings/llm", json={role: provider, "routing": {"mode": mode}}).raise_for_status()
    client.put("/settings/persona", json=cases["persona"]).raise_for_status()
    client.put("/settings/websearch", json={"policy": "auto"}).raise_for_status()


def run(client, cases: dict, search: FixtureSearch, *, repeats: int) -> list[dict]:
    records = []
    for repeat in range(1, repeats + 1):
        for conversation in cases["conversations"]:
            session = f"eval-{uuid.uuid4().hex[:8]}"
            for index, turn in enumerate(conversation["turns"]):
                search.results = turn.get("search_results", [])
                search.error = turn.get("search_error", False)
                before = len(client.get("/websearch/log").json()["entries"])
                started = time.perf_counter()
                response = client.post("/conversation", json={
                    "session_id": session, "conversation_id": session, "channel": "reachy",
                    "text": turn["text"], "input_modality": "voice",
                })
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                reply = response.json()["reply"]
                entries = client.get("/websearch/log").json()["entries"]
                searched = len(entries) > before
                query = _newest_query(entries) if searched else None
                record = {
                    "conversation": conversation["id"], "repeat": repeat, "turn": index,
                    "category": turn.get("category"), "text": turn["text"], "reply": reply,
                    "searched": searched, "query": query, "elapsed_ms": elapsed_ms,
                }
                if "expect" in turn:
                    record["failures"] = score_turn(turn["expect"], reply, searched=searched, query=query)
                records.append(record)
                print(_line(record), flush=True)
    return records


def _newest_query(entries: list[dict]) -> str | None:
    return max(entries, key=lambda e: e["at"])["query"] if entries else None


def _line(record: dict) -> str:
    verdict = "-" if "failures" not in record else ("PASS" if not record["failures"] else "FAIL")
    detail = "; ".join(record.get("failures", []))
    return f"[{verdict}] r{record['repeat']} {record['conversation']}#{record['turn']} {record['elapsed_ms']} ms {detail}"


def summarize(records: list[dict]) -> dict:
    scored = [r for r in records if "failures" in r]
    by_category: dict[str, list[bool]] = defaultdict(list)
    for record in scored:
        by_category[record["category"]].append(not record["failures"])
    elapsed = sorted(r["elapsed_ms"] for r in records)
    return {
        "overall": _rate([not r["failures"] for r in scored]),
        "categories": {name: _rate(results) for name, results in sorted(by_category.items())},
        "elapsed_ms": {
            "p50": statistics.median(elapsed) if elapsed else None,
            "p95": elapsed[max(0, round(0.95 * len(elapsed)) - 1)] if elapsed else None,
            "max": elapsed[-1] if elapsed else None,
        },
    }


def _rate(results: list[bool]) -> dict:
    passed = sum(results)
    return {"passed": passed, "total": len(results), "rate": round(passed / len(results), 3) if results else None}


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
            cwd=Path(__file__).parent,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--base-url", required=True, help="OpenAI-compatible base URL")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", help="name of the environment variable holding the API key")
    parser.add_argument("--role", choices=("local", "cloud"), default="local")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True, help="directory for transcript.jsonl and summary.json")
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    cases = json.loads(args.cases.read_text())
    api_key = os.environ[args.api_key_env] if args.api_key_env else None
    search = FixtureSearch()
    with TestClient(build_app(search)) as client:
        configure(client, cases, base_url=args.base_url, model=args.model, api_key=api_key, role=args.role)
        records = run(client, cases, search, repeats=args.repeats)

    summary = {
        "cases": args.cases.name, "cases_version": cases["version"], "model": args.model,
        "base_url": args.base_url, "role": args.role, "repeats": args.repeats,
        "commit": _git_commit(), "finished_at": datetime.now(UTC).isoformat(), **summarize(records),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "transcript.jsonl").open("w") as transcript:
        for record in records:
            transcript.write(json.dumps(record) + "\n")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("overall", "categories", "elapsed_ms")}, indent=2))


if __name__ == "__main__":
    main()
