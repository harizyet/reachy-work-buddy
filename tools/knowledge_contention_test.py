"""Does building the knowledge index slow down speech and chat? (Phase 44B deployment gate, owner decision D14. Bounded; prepared, not run.)

Three phases of equal length:
  A  foreground only      a speech workload and a chat workload, one request of each kind in flight at a time
  B  foreground + index   the same, with the real indexing worker (IndexingWorker with the real MiniLM embedder) building an index over a
                          synthetic corpus in a SCRATCH database, never the production one
  C  indexing only        the worker alone, for throughput
Speech is either faster-whisper run in this process on the host's CPU (the hub's STT is CPU faster-whisper, so this is the representative
contender), or a POST to a transcription endpoint. Chat is POSTs to an OpenAI-compatible endpoint (the local vLLM).

It is bounded by construction. Resource limits: torch threads for the worker, a nice value for the whole process, an optional CPU
affinity, one request in flight per workload, small chat answers. Automatic stop conditions, checked every second: host load average,
available memory, an error-rate ceiling, chat p95 above a multiple of the phase-A baseline (three breaches in a row), a stop file, and a
hard cap on total time. A stop ends all workloads at once, skips the remaining phases, drops the scratch database and records why.

It refuses real services without --confirm-owner-approved. It writes nothing but the report and its scratch database.

  python tools/knowledge_contention_test.py --chat-url http://localhost:8003/v1/chat/completions --chat-model reachy-local \\
      --stt local --stt-model base.en --stt-audio clip.wav --stt-threads 4 \\
      --index worker --scratch-admin-url postgresql://USER:PW@127.0.0.1:PORT/postgres --scale 2000 \\
      --seconds 90 --embed-threads 2 --nice 10 --abort-load 14 --abort-min-available-gb 3 --max-total-seconds 720 \\
      --stop-file /tmp/stop-contention --confirm-owner-approved --out report.json

  python tools/knowledge_contention_test.py --self-test     # stub servers and a CPU burner; nothing else is touched
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, round(p / 100 * len(ordered) + 0.5) - 1)]


def summarize(latencies: list[float], errors: int, extra: dict | None = None) -> dict:
    out = {"requests": len(latencies) + errors, "errors": errors}
    if latencies:
        out |= {"p50_s": round(statistics.median(latencies), 3), "p95_s": round(percentile(latencies, 95), 3), "max_s": round(max(latencies), 3)}
    return out | (extra or {})


def meminfo_available_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 / 1024
    return float("inf")


@dataclass
class Stats:
    speech: list[float] = field(default_factory=list)
    speech_errors: int = 0
    chat: list[float] = field(default_factory=list)
    chat_errors: int = 0
    chat_tokens: int = 0
    ttft: list[float] = field(default_factory=list)
    speech_streak: int = 0  # consecutive failures, reset by a success
    chat_streak: int = 0


@dataclass
class Control:
    """One place that says the test must end. Every workload and the monitor look at it."""

    async_stop: asyncio.Event = field(default_factory=asyncio.Event)
    thread_stop: threading.Event = field(default_factory=threading.Event)
    aborted: dict | None = None
    started: float = field(default_factory=time.monotonic)

    def abort(self, reason: str, **detail) -> None:
        if self.aborted is None:
            self.aborted = {"reason": reason, "after_seconds": round(time.monotonic() - self.started, 1), **detail}
        self.async_stop.set()
        self.thread_stop.set()


# ---- workloads --------------------------------------------------------------------------------------------------

async def chat_loop(client: httpx.AsyncClient, args, stats: Stats, stop: asyncio.Event) -> None:
    prompts = [
        "In two sentences, explain why a retry limit on a job queue is useful.",
        "Name three things to check before deploying a database migration.",
        "Summarise in one sentence why backups should be restored as a test.",
    ]
    n = 0
    while not stop.is_set():
        body = {"model": args.chat_model, "temperature": 0, "max_tokens": args.chat_max_tokens, "stream": True,
                "stream_options": {"include_usage": True}, "messages": [{"role": "user", "content": prompts[n % len(prompts)]}]}
        n += 1
        started = time.perf_counter()
        first = None
        tokens = 0
        try:
            async with client.stream("POST", args.chat_url, json=body, timeout=120) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[6:])
                    if first is None and any((c.get("delta") or {}).get("content") for c in chunk.get("choices") or []):
                        first = time.perf_counter() - started
                    tokens = int((chunk.get("usage") or {}).get("completion_tokens", tokens))
            stats.chat.append(time.perf_counter() - started)
            stats.chat_tokens += tokens
            stats.chat_streak = 0
            if first is not None:
                stats.ttft.append(first)
        except (httpx.HTTPError, ValueError):
            stats.chat_errors += 1
            stats.chat_streak += 1
            await asyncio.sleep(0.5)


async def speech_loop_http(client: httpx.AsyncClient, args, audio: bytes, stats: Stats, stop: asyncio.Event) -> None:
    headers = {"X-Reachy-Service-Token": args.stt_token} if args.stt_token else {}
    while not stop.is_set():
        started = time.perf_counter()
        try:
            response = await client.post(args.stt_url, files={args.stt_field: ("clip.wav", audio, "audio/wav")}, headers=headers, timeout=120)
            response.raise_for_status()
            stats.speech.append(time.perf_counter() - started)
            stats.speech_streak = 0
        except httpx.HTTPError:
            stats.speech_errors += 1
            stats.speech_streak += 1
            await asyncio.sleep(0.5)


def speech_thread_local(args, stats: Stats, stop: threading.Event) -> threading.Thread:
    """faster-whisper on the host's CPU, as the hub's speech-to-text runs, transcribing the clip again and again."""
    from faster_whisper import WhisperModel

    if not hasattr(args, "_whisper"):
        args._whisper = WhisperModel(args.stt_model, device="cpu", compute_type="int8", cpu_threads=args.stt_threads)
    model, clip = args._whisper, args.stt_audio

    def run():
        while not stop.is_set():
            started = time.perf_counter()
            try:
                segments, _ = model.transcribe(clip, vad_filter=False)
                list(segments)
                stats.speech.append(time.perf_counter() - started)
                stats.speech_streak = 0
            except Exception:  # noqa: BLE001  a decoding problem is counted, not fatal to the test
                stats.speech_errors += 1
                stats.speech_streak += 1
                time.sleep(0.5)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def make_embedder(kind: str, threads: int):
    if kind == "minilm":
        import torch
        from companion_core.rag.embeddings import embed

        torch.set_num_threads(threads)
        embed(["warm up"])
        return embed

    def burn(batch):  # a CPU-bound stand-in for tests: no model, no download
        end = time.perf_counter() + 0.02
        while time.perf_counter() < end:
            sum(i * i for i in range(2000))
        return [[0.0] * 384 for _ in batch]

    return burn


def indexing_thread_embed(embedder, stop: threading.Event, result: dict) -> threading.Thread:
    batch = [f"Priya: we discussed topic {i} and the retry limit of five for the queue" for i in range(16)]

    def run():
        done, started = 0, time.perf_counter()
        while not stop.is_set():
            embedder(batch)
            done += len(batch)
        result["items"], result["seconds"] = done, time.perf_counter() - started

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


class Scratch:
    """A throwaway database on a disposable server, seeded with the synthetic corpus the overhead measurement uses."""

    def __init__(self, admin_url: str, scale: int, embedder) -> None:
        import psycopg

        sys.path.insert(0, str(ROOT / "services/companion-core/benchmarks/knowledge_retrieval"))
        from uuid import uuid4

        import index_overhead as overhead
        from companion_core.migrations.__main__ import upgrade
        from companion_core.secrets import Keyring

        self.admin, self.name, self.embedder = admin_url, "contention_" + uuid4().hex[:10], embedder
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{self.name}"')
        self.dsn = psycopg.conninfo.make_conninfo(admin_url, dbname=self.name)
        upgrade(self.dsn, Keyring("scratch", {"scratch": b"\x05" * 32}))
        import random

        with psycopg.connect(self.dsn) as conn:
            overhead.seed(conn, scale, max(scale // 50, 2), random.Random(44))
        self.requeue_sql = (
            "INSERT INTO knowledge_outbox (source_type, source_id) SELECT 'note', id FROM notes UNION ALL SELECT 'task', id FROM tasks "
            "UNION ALL SELECT 'memory', id FROM memories UNION ALL SELECT DISTINCT 'document', document_id FROM document_chunks "
            "UNION ALL SELECT 'meeting', id FROM meetings ON CONFLICT (source_type, source_id) DO UPDATE SET gen = knowledge_outbox.gen + 1"
        )

    def worker_thread(self, stop: threading.Event, result: dict, tmp_audio: str) -> threading.Thread:
        import psycopg
        from companion_core.knowledge.index import PostgresKnowledgeIndex
        from companion_core.knowledge.outbox import PostgresOutbox
        from companion_core.knowledge.sources import build_adapters
        from companion_core.knowledge.worker import IndexingWorker
        from companion_core.meetings.postgres_store import PostgresMeetingStore
        from companion_core.memory.postgres_store import PostgresMemoryStore
        from companion_core.planner.postgres_store import PostgresPlannerStore
        from companion_core.rag.postgres_store import PostgresDocumentStore
        from companion_core.tasks.postgres_store import PostgresTaskStore

        async def go():
            memory, planner, tasks = await PostgresMemoryStore.connect(self.dsn), await PostgresPlannerStore.connect(self.dsn), await PostgresTaskStore.connect(self.dsn)
            documents, meetings = await PostgresDocumentStore.connect(self.dsn), await PostgresMeetingStore.connect(self.dsn, audio_dir=tmp_audio)
            index, outbox = await PostgresKnowledgeIndex.connect(self.dsn), await PostgresOutbox.connect(self.dsn)
            worker = IndexingWorker(adapters=build_adapters(memory=memory, documents=documents, meetings=meetings, planner=planner, tasks=tasks),
                                    index=index, outbox=outbox, embed_fn=self.embedder, embedding_model="contention-test")
            done, started = 0, time.perf_counter()
            while not stop.is_set():
                step = await worker.run_once()
                done += step.upserted
                if not step.processed:  # drained: queue everything again so the worker stays busy for the whole phase
                    with psycopg.connect(self.dsn, autocommit=True) as conn:
                        conn.execute("UPDATE knowledge_items SET source_version = 'stale'")  # force re-embedding, as a real rebuild would
                        conn.execute(self.requeue_sql)
            result["items"], result["seconds"] = done, time.perf_counter() - started
            for part in (memory, planner, tasks, documents, meetings, index, outbox):
                await part.close()

        thread = threading.Thread(target=lambda: asyncio.run(go()), daemon=True)
        thread.start()
        return thread

    def progress(self) -> dict:
        import psycopg

        with psycopg.connect(self.dsn, autocommit=True, connect_timeout=3) as conn:
            return {"outbox_pending": conn.execute("SELECT count(*) FROM knowledge_outbox").fetchone()[0],
                    "indexed_rows": conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]}

    def drop(self) -> bool:
        import psycopg

        try:
            with psycopg.connect(self.admin, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')
            return True
        except psycopg.Error:
            return False


# ---- the bounds -------------------------------------------------------------------------------------------------

def proc_cpu_seconds() -> float:
    t = os.times()
    return t.user + t.system


def thread_count() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("Threads:"):
            return int(line.split()[1])
    return 0


def host_cpu_times() -> tuple[float, float]:
    fields = [float(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    return sum(fields) - fields[3] - fields[4], sum(fields)  # busy (not idle/iowait), total


async def observe(args, control: Control, scratch, samples: list[dict], health: dict) -> None:
    """Once a second: host load, memory, this process's CPU/threads/RSS, event-loop lag, and (every 5 s) queue depth and the health of the
    production services. A production service failing twice in a row, or answering slower than the limit twice, ends the test."""
    last_cpu, last_host, last_t = proc_cpu_seconds(), host_cpu_times(), time.monotonic()
    strikes: dict[str, int] = {}
    tick = 0
    async with httpx.AsyncClient() as client:
        while not control.async_stop.is_set():
            before = time.monotonic()
            await asyncio.sleep(1.0)
            lag = time.monotonic() - before - 1.0
            now, cpu, host = time.monotonic(), proc_cpu_seconds(), host_cpu_times()
            rss = int(next(ln for ln in Path("/proc/self/status").read_text().splitlines() if ln.startswith("VmRSS:")).split()[1]) / 1024
            sample = {"load1": round(os.getloadavg()[0], 2), "mem_available_gb": round(meminfo_available_gb(), 2),
                      "proc_cpu_cores": round((cpu - last_cpu) / (now - last_t), 2), "threads": thread_count(), "rss_mb": round(rss),
                      "host_cpu_pct": round(100 * (host[0] - last_host[0]) / max(host[1] - last_host[1], 1), 1), "loop_lag_ms": round(1000 * lag)}
            last_cpu, last_host, last_t = cpu, host, now
            tick += 1
            if tick % 5 == 0:
                if scratch is not None:
                    sample |= scratch.progress()
                for url in args.health_url:
                    t0 = time.perf_counter()
                    try:
                        r = await client.get(url, timeout=3)
                        ok, took = r.status_code == 200, time.perf_counter() - t0
                    except httpx.HTTPError:
                        ok, took = False, 3.0
                    health.setdefault(url, []).append({"ok": ok, "s": round(took, 3)})
                    strikes[url] = strikes.get(url, 0) + 1 if (not ok or took > args.abort_health_seconds) else 0
                    if strikes[url] >= 2:
                        control.abort("production service unhealthy or slow twice in a row", url=url, ok=ok, seconds=round(took, 3))
            samples.append(sample)


async def monitor(args, control: Control, stats: Stats, baseline: dict, phase: str) -> None:
    breaches = {"chat": 0, "speech": 0}
    while not control.async_stop.is_set():
        await asyncio.sleep(1.0)
        if time.monotonic() - control.started > args.max_total_seconds:
            control.abort("hard time cap reached", cap_seconds=args.max_total_seconds)
        elif args.stop_file and Path(args.stop_file).exists():
            control.abort("stop file present", file=args.stop_file)
        elif os.getloadavg()[0] > args.abort_load:
            control.abort("host load average above the limit", load=round(os.getloadavg()[0], 1), limit=args.abort_load)
        elif meminfo_available_gb() < args.abort_min_available_gb:
            control.abort("available memory below the limit", available_gb=round(meminfo_available_gb(), 1), limit=args.abort_min_available_gb)
        else:
            for kind, ok, errors, streak in (("chat", stats.chat, stats.chat_errors, stats.chat_streak),
                                             ("speech", stats.speech, stats.speech_errors, stats.speech_streak)):
                attempts = len(ok) + errors
                if streak >= args.abort_consecutive_failures:
                    control.abort(f"{kind} failed repeatedly", consecutive=streak)
                elif errors >= args.abort_phase_errors:
                    control.abort(f"{kind} errors in this phase reached the limit", errors=errors, attempts=attempts)
                elif attempts >= 10 and errors / attempts > args.abort_error_rate:
                    control.abort(f"{kind} error rate above the limit", errors=errors, attempts=attempts)
                recent = ok[-20:]
                if phase == "B" and baseline.get(kind + "_p95") and len(recent) >= (10 if kind == "chat" else 3):
                    breaches[kind] = breaches[kind] + 1 if percentile(recent, 95) > args.abort_chat_p95_ratio * baseline[kind + "_p95"] else 0
                    if breaches[kind] >= 3:
                        control.abort(f"{kind} p95 above the allowed multiple of the baseline three checks in a row",
                                      p95_s=round(percentile(recent, 95), 3), baseline_p95_s=baseline[kind + "_p95"], ratio=args.abort_chat_p95_ratio)


def summarize_samples(samples: list[dict]) -> dict:
    out = {}
    for key in ("load1", "mem_available_gb", "proc_cpu_cores", "threads", "rss_mb", "host_cpu_pct", "loop_lag_ms"):
        values = [x[key] for x in samples if key in x]
        if values:
            out[key] = ({"min": min(values), "max": max(values)} if key == "mem_available_gb" else {"mean": round(statistics.mean(values), 2), "max": max(values)})
    queue = [x for x in samples if "outbox_pending" in x]
    if queue:
        out["queue"] = {"pending_first": queue[0]["outbox_pending"], "pending_last": queue[-1]["outbox_pending"],
                        "indexed_first": queue[0]["indexed_rows"], "indexed_last": queue[-1]["indexed_rows"]}
    return out


async def run_phase(name, args, audio, embedder, scratch, control, baseline, foreground: bool, indexing: bool) -> dict:
    stats = Stats()
    control.async_stop = asyncio.Event()
    thread_stop = threading.Event()
    control.thread_stop = thread_stop
    result: dict = {}
    threads = []
    out: dict = {"phase": name}
    load_before = os.getloadavg()[0]
    samples: list[dict] = []
    health: dict = {}
    async with httpx.AsyncClient() as client:
        tasks = [asyncio.create_task(monitor(args, control, stats, baseline, name)),
                 asyncio.create_task(observe(args, control, scratch if indexing else None, samples, health))]
        if foreground:
            tasks.append(asyncio.create_task(chat_loop(client, args, stats, control.async_stop)))
            if args.stt == "http":
                tasks.append(asyncio.create_task(speech_loop_http(client, args, audio, stats, control.async_stop)))
            elif args.stt == "local":
                threads.append(speech_thread_local(args, stats, thread_stop))
        if indexing:
            threads.append(scratch.worker_thread(thread_stop, result, args.scratch_audio_dir) if args.index == "worker" else indexing_thread_embed(embedder, thread_stop, result))
        started = time.monotonic()
        while time.monotonic() - started < args.seconds and not control.async_stop.is_set():
            await asyncio.sleep(0.25)
        control.async_stop.set()
        thread_stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    for t in threads:
        t.join(timeout=60)
    elapsed = time.monotonic() - started
    if foreground:
        out["speech"] = summarize(stats.speech, stats.speech_errors)
        out["chat"] = summarize(stats.chat, stats.chat_errors,
                                {"completion_tokens_per_s": round(stats.chat_tokens / elapsed, 1) if stats.chat_tokens else None})
        if stats.ttft:
            out["chat"] |= {"ttft_p50_s": round(statistics.median(stats.ttft), 3), "ttft_p95_s": round(percentile(stats.ttft, 95), 3)}
    if indexing and result:
        out["indexing"] = {"items": result["items"], "items_per_s": round(result["items"] / max(result["seconds"], 1e-9), 1)}
    out["resources"] = summarize_samples(samples)
    out["production_health"] = {u: {"checks": len(h), "failed": sum(not x["ok"] for x in h), "max_s": max((x["s"] for x in h), default=None)} for u, h in health.items()}
    out |= {"seconds": round(elapsed, 1), "load_average_start": round(load_before, 2), "load_average_end": round(os.getloadavg()[0], 2),
            "memory_available_gb_end": round(meminfo_available_gb(), 1)}
    return out


def compare(a: dict, b: dict) -> dict:
    delta = {}
    for kind in ("speech", "chat"):
        pa, pb = a.get(kind, {}), b.get(kind, {})
        if "p50_s" in pa and "p50_s" in pb:
            delta[kind] = {"p50_change_pct": round(100 * (pb["p50_s"] / pa["p50_s"] - 1), 1), "p95_change_pct": round(100 * (pb["p95_s"] / pa["p95_s"] - 1), 1),
                           "errors_added": pb["errors"] - pa["errors"]}
            if kind == "chat" and "ttft_p50_s" in pa and "ttft_p50_s" in pb:
                delta[kind]["ttft_p50_change_pct"] = round(100 * (pb["ttft_p50_s"] / pa["ttft_p50_s"] - 1), 1)
            if kind == "chat" and pa.get("completion_tokens_per_s") and pb.get("completion_tokens_per_s"):
                delta[kind]["throughput_change_pct"] = round(100 * (pb["completion_tokens_per_s"] / pa["completion_tokens_per_s"] - 1), 1)
    return delta


async def main_async(args) -> dict:
    audio = Path(args.stt_audio).read_bytes() if args.stt_audio and args.stt == "http" else b"RIFF0000WAVE"
    if args.nice:
        os.nice(args.nice)
    if args.cpus:
        os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[: args.cpus]))
    control = Control()
    report = {"limits": {k: getattr(args, k) for k in ("seconds", "embed_threads", "nice", "cpus", "stt_threads", "chat_max_tokens", "abort_load",
                                                         "abort_min_available_gb", "abort_error_rate", "abort_consecutive_failures", "abort_phase_errors", "abort_health_seconds", "recovery_seconds", "health_url", "abort_chat_p95_ratio", "max_total_seconds", "scale")},
              "workloads": {"speech": args.stt, "chat": args.chat_url, "indexing": args.index, "embedder": args.embed},
              "host": {"cpus": os.cpu_count(), "load_average_start": round(os.getloadavg()[0], 2), "memory_available_gb_start": round(meminfo_available_gb(), 1)}}
    embedder = make_embedder(args.embed, args.embed_threads)
    scratch = Scratch(args.scratch_admin_url, args.scale, embedder) if args.index == "worker" else None
    report["cleanup"] = {"scratch_database": scratch.name if scratch else None}
    try:
        baseline: dict = {}
        report["A_foreground_only"] = await run_phase("A", args, audio, embedder, scratch, control, baseline, True, False)
        baseline["chat_p95"] = report["A_foreground_only"]["chat"].get("p95_s")
        baseline["speech_p95"] = report["A_foreground_only"].get("speech", {}).get("p95_s")
        if control.aborted is None:
            report["B_foreground_plus_indexing"] = await run_phase("B", args, audio, embedder, scratch, control, baseline, True, True)
        if control.aborted is None:
            report["C_indexing_only"] = await run_phase("C", args, audio, embedder, scratch, control, baseline, False, True)
        if control.aborted is None and args.recovery_seconds:
            args.seconds = args.recovery_seconds  # a short foreground-only check after the indexer has stopped
            report["R_recovery"] = await run_phase("R", args, audio, embedder, scratch, control, baseline, True, False)
    finally:
        if scratch:
            report["cleanup"]["scratch_database_dropped"] = scratch.drop()
    report["aborted"] = control.aborted
    report["process_after"] = {"threads": thread_count(), "load_average": round(os.getloadavg()[0], 2), "memory_available_gb": round(meminfo_available_gb(), 1)}
    if "R_recovery" in report:
        report["recovery_vs_baseline"] = compare(report["A_foreground_only"], report["R_recovery"])
    if "B_foreground_plus_indexing" in report:
        report["change_from_A_to_B"] = compare(report["A_foreground_only"], report["B_foreground_plus_indexing"])
    if "C_indexing_only" in report and "indexing" in report.get("B_foreground_plus_indexing", {}):
        report["indexing_throughput_items_per_s"] = {"with_foreground": report["B_foreground_plus_indexing"]["indexing"]["items_per_s"],
                                                       "alone": report["C_indexing_only"]["indexing"]["items_per_s"]}
    return report


class _Stub(BaseHTTPRequestHandler):
    delay = 0.05
    fail = False

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        time.sleep(self.delay)
        if request.get("stream") and not self.fail:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in ({"choices": [{"delta": {"content": "ok"}}]}, {"choices": [], "usage": {"completion_tokens": 20}}):
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        if self.fail:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps({"segments": [], "usage": {"completion_tokens": 20}, "choices": [{"message": {"content": "ok"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start_stub(delay: float, fail: bool = False) -> tuple[ThreadingHTTPServer, str]:
    handler = type("H", (_Stub,), {"delay": delay, "fail": fail})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chat-url")
    p.add_argument("--chat-model", default="reachy-local")
    p.add_argument("--chat-max-tokens", type=int, default=64)
    p.add_argument("--stt", choices=("local", "http", "none"), default="local")
    p.add_argument("--stt-model", default="base.en")
    p.add_argument("--stt-threads", type=int, default=4)
    p.add_argument("--stt-audio")
    p.add_argument("--stt-url")
    p.add_argument("--stt-field", default="file")
    p.add_argument("--stt-token")
    p.add_argument("--index", choices=("worker", "embed"), default="worker")
    p.add_argument("--embed", choices=("minilm", "burn"), default="minilm")
    p.add_argument("--embed-threads", type=int, default=2)
    p.add_argument("--scratch-admin-url", help="a disposable PostgreSQL server (never production) where a scratch database is created and dropped")
    p.add_argument("--scratch-audio-dir", default="/tmp/contention-audio")
    p.add_argument("--scale", type=int, default=2000)
    p.add_argument("--seconds", type=float, default=90)
    p.add_argument("--nice", type=int, default=10)
    p.add_argument("--cpus", type=int, default=0, help="restrict this process to the first N CPUs (0 = no restriction)")
    p.add_argument("--abort-load", type=float, default=14.0)
    p.add_argument("--abort-min-available-gb", type=float, default=3.0)
    p.add_argument("--abort-error-rate", type=float, default=0.05, help="error fraction (after 10 attempts) that ends the test")
    p.add_argument("--abort-consecutive-failures", type=int, default=2)
    p.add_argument("--abort-phase-errors", type=int, default=3, help="total errors of one kind in a phase that end the test")
    p.add_argument("--abort-health-seconds", type=float, default=3.0, help="a production health check slower than this counts as a strike")
    p.add_argument("--health-url", action="append", default=[], help="production health endpoint to watch (repeatable); two bad checks in a row end the test")
    p.add_argument("--recovery-seconds", type=float, default=20)
    p.add_argument("--abort-chat-p95-ratio", type=float, default=3.0)
    p.add_argument("--max-total-seconds", type=float, default=720)
    p.add_argument("--stop-file")
    p.add_argument("--confirm-owner-approved", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--self-test-fail-chat", action="store_true", help="with --self-test: make the chat stub fail, to exercise the abort path")
    p.add_argument("--out")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    servers = []
    if args.self_test:
        chat, args.chat_url = start_stub(0.08, fail=args.self_test_fail_chat)
        servers = [chat]
        args.stt, args.embed, args.seconds = "none", "burn", args.seconds if args.health_url else min(args.seconds, 3)
        if not args.scratch_admin_url:
            args.index = "embed"  # the real worker needs a scratch server; --self-test --index worker --scratch-admin-url exercises it with the CPU burner
        args.nice, args.max_total_seconds, args.recovery_seconds = 0, min(args.max_total_seconds, 60), min(args.recovery_seconds, 2)
    elif not args.chat_url:
        print("give --chat-url (or --self-test)", file=sys.stderr)
        return 2
    elif not args.confirm_owner_approved:
        print(f"this would send requests to {args.chat_url} and use up to {3 * args.seconds:.0f} s of CPU on this host beside real use; "
              "re-run with --confirm-owner-approved once the owner has agreed", file=sys.stderr)
        return 2
    elif args.index == "worker" and not args.scratch_admin_url:
        print("--index worker needs --scratch-admin-url (a disposable PostgreSQL server, never the production database)", file=sys.stderr)
        return 2
    elif args.stt == "local" and not args.stt_audio:
        print("--stt local needs --stt-audio (a short clip)", file=sys.stderr)
        return 2
    elif args.stt == "http" and not args.stt_url:
        print("--stt http needs --stt-url", file=sys.stderr)
        return 2
    try:
        report = asyncio.run(main_async(args))
    finally:
        for s in servers:
            s.shutdown()
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
