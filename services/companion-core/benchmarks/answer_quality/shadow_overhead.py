"""Measure the overhead of the knowledge shadow (B1a lexical, status routing, builder) against a scratch Postgres with the invented corpus indexed.

    KBENCH_DATABASE_URL=postgresql://postgres:aq@127.0.0.1:55444/postgres python shadow_overhead.py --out results/shadow-overhead.json

Reports per-job latency (route or retrieve, build, total), the cost of `submit()` on the request path, process CPU per job, peak memory, whether any
embedding model or torch was loaded, queue behaviour under a burst, and the telemetry file size per job. No model server, no production data."""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aq import cases as caselib
from companion_core.knowledge.retrieval import B1A, Retriever
from companion_core.knowledge.search import PostgresSearch
from companion_core.knowledge.shadow import KnowledgeShadow, ShadowTurn
from kbench.corpus import build_corpus
from kbench.pg_env import build_pg_corpus, hashing_embed_384


def pct(values, p):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(p / 100 * len(values)))], 2) if values else None


async def main(out: str | None) -> None:
    spec = (await build_corpus()).spec
    env = await build_pg_corpus(spec, hashing_embed_384, "hashing-bag-of-words-384")
    log = Path(tempfile.mkdtemp()) / "ks.jsonl"
    shadow = KnowledgeShadow(
        retriever=Retriever(search=PostgresSearch(env.pool), adapters=env.adapters, config=B1A, clock=lambda: datetime.now(UTC)),
        tasks=env.stores[2], planner=env.stores[1], log_path=str(log),
    )
    questions = [c["question"] for s in ("dev", "dev2", "holdout") for c in caselib.load_cases(s)]  # questions only; nothing is scored or tuned
    turns = [ShadowTurn("bench", q, "text", "work-private", "generic_chat", False) for q in questions]
    modules_before = set(sys.modules)
    # direct job cost, serial
    per_job, cpu0 = [], time.process_time()
    for t in turns:
        t0 = time.perf_counter()
        row = await shadow._measure(t)
        per_job.append((time.perf_counter() - t0) * 1000)
        shadow._write(t, {**row, "outcome": "ok", "total_ms": per_job[-1]})
    cpu_per_job = (time.process_time() - cpu0) / len(turns) * 1000
    loaded = sorted(m for m in set(sys.modules) - modules_before if m.split(".")[0] in ("torch", "sentence_transformers", "transformers"))
    # request-path cost of submit, and a burst larger than the queue
    t0 = time.perf_counter()
    for t in turns[:50]:
        shadow.submit(t)
    submit_us = (time.perf_counter() - t0) / 50 * 1e6
    await shadow.drain()
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    retrieval = [r["total_ms"] for r in rows[: len(turns)] if r.get("path") == "retrieval"]
    status = [r["total_ms"] for r in rows[: len(turns)] if r.get("path") == "status"]
    result = {
        "jobs": len(turns), "job_ms": {"p50": pct(per_job, 50), "p95": pct(per_job, 95), "max": round(max(per_job), 2), "mean": round(statistics.mean(per_job), 2)},
        "retrieval_path_ms": {"n": len(retrieval), "p50": pct(retrieval, 50), "p95": pct(retrieval, 95)}, "status_path_ms": {"n": len(status), "p50": pct(status, 50), "p95": pct(status, 95)},
        "cpu_ms_per_job": round(cpu_per_job, 2), "submit_microseconds_on_request_path": round(submit_us, 1),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        "embedding_or_torch_modules_loaded_by_the_shadow": loaded,
        "burst_of_50": {"dropped_busy": shadow.counters["dropped_busy"], "queue_limit": shadow.queue_size, "measured_after_burst": shadow.counters["measured"] - len(turns)},
        "telemetry_bytes_per_job": round(log.stat().st_size / len(rows), 1), "telemetry_file_mode": oct(log.stat().st_mode & 0o777),
        "counters": shadow.summary(),
    }
    await env.close()
    text = json.dumps(result, indent=1)
    if out:
        Path(out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out")
    asyncio.run(main(p.parse_args().out))
