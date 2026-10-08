"""Does building the knowledge index slow down speech and chat? (Phase 44B deployment gate; prepared, not yet run against production.)

Three phases of the same length, each driving the workloads that are named:
  A  foreground only      speech (POST audio to a transcription endpoint) and chat (POST to an OpenAI-compatible endpoint), one request
                          of each kind in flight at a time
  B  foreground + index   the same, with the indexing workload (embedding batches of 16 on N torch threads) running beside them
  C  indexing only        the embedding workload alone, for throughput
It reports per-workload latency p50/p95/max, error counts, tokens per second for chat, embedding throughput, and the host's load, then
the change from A to B. Nothing is written anywhere except the JSON report.

It calls the services it is given, so against the homelab it competes with real use and with the owner's own GPU and CPU work. It will
not start without --confirm-owner-approved. Run it when the owner approves, with the robot idle, and with indexing OFF in core (this
tool supplies its own embedding load):

  python tools/knowledge_contention_test.py \\
      --stt-url http://localhost:8011/transcribe --stt-audio clip.wav \\
      --chat-url http://localhost:8003/v1/chat/completions --chat-model reachy-local \\
      --embed minilm --embed-threads 2 --seconds 60 --confirm-owner-approved

  python tools/knowledge_contention_test.py --self-test     # local stub servers and a CPU burner; touches nothing else
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx


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


async def speech_loop(client: httpx.AsyncClient, url: str, audio: bytes, field: str, stop: asyncio.Event, token: str | None) -> dict:
    latencies, errors = [], 0
    headers = {"X-Reachy-Service-Token": token} if token else {}
    while not stop.is_set():
        started = time.perf_counter()
        try:
            response = await client.post(url, files={field: ("clip.wav", audio, "audio/wav")}, headers=headers, timeout=120)
            response.raise_for_status()
            latencies.append(time.perf_counter() - started)
        except httpx.HTTPError:
            errors += 1
            await asyncio.sleep(0.5)
    return summarize(latencies, errors)


async def chat_loop(client: httpx.AsyncClient, url: str, model: str, stop: asyncio.Event, max_tokens: int) -> dict:
    latencies, errors, tokens = [], 0, 0
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": "In two sentences, explain why a retry limit on a job queue is useful."}]}
    started_all = time.perf_counter()
    while not stop.is_set():
        started = time.perf_counter()
        try:
            response = await client.post(url, json=body, timeout=120)
            response.raise_for_status()
            latencies.append(time.perf_counter() - started)
            tokens += int((response.json().get("usage") or {}).get("completion_tokens", 0))
        except (httpx.HTTPError, ValueError):
            errors += 1
            await asyncio.sleep(0.5)
    elapsed = time.perf_counter() - started_all
    return summarize(latencies, errors, {"completion_tokens_per_s": round(tokens / elapsed, 1) if tokens else None})


def make_embedder(kind: str, threads: int):
    if kind == "minilm":
        import torch
        from companion_core.rag.embeddings import embed

        torch.set_num_threads(threads)
        embed(["warm up"])
        return lambda batch: embed(batch)

    def burn(batch):  # a CPU-bound stand-in for tests: no model, no download
        end = time.perf_counter() + 0.02
        while time.perf_counter() < end:
            sum(i * i for i in range(2000))
        return batch

    return burn


def embedding_thread(embedder, stop: threading.Event, result: dict) -> threading.Thread:
    batch = [f"Priya: we discussed topic {i} and the retry limit of five for the queue" for i in range(16)]

    def run():
        done = 0
        started = time.perf_counter()
        while not stop.is_set():
            embedder(batch)
            done += len(batch)
        result["items"], result["seconds"] = done, time.perf_counter() - started

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


async def run_phase(name, args, audio, embedder, with_foreground: bool, with_indexing: bool) -> dict:
    stop = asyncio.Event()
    stop_thread = threading.Event()
    embed_result: dict = {}
    thread = embedding_thread(embedder, stop_thread, embed_result) if with_indexing else None
    load_before = os.getloadavg()[0]
    out: dict = {"phase": name}
    async with httpx.AsyncClient() as client:
        tasks = []
        if with_foreground:
            tasks = [asyncio.create_task(speech_loop(client, args.stt_url, audio, args.stt_field, stop, args.stt_token)),
                     asyncio.create_task(chat_loop(client, args.chat_url, args.chat_model, stop, args.chat_max_tokens))]
        await asyncio.sleep(args.seconds)
        stop.set()
        stop_thread.set()
        results = await asyncio.gather(*tasks) if tasks else []
    if thread:
        thread.join(timeout=30)
    if with_foreground:
        out["speech"], out["chat"] = results
    if with_indexing:
        out["indexing"] = {"items_per_s": round(embed_result["items"] / embed_result["seconds"], 1), "items": embed_result["items"]}
    out["load_average_start"] = round(load_before, 2)
    out["load_average_end"] = round(os.getloadavg()[0], 2)
    return out


def compare(a: dict, b: dict) -> dict:
    delta = {}
    for kind in ("speech", "chat"):
        pa, pb = a[kind], b[kind]
        if "p50_s" in pa and "p50_s" in pb:
            delta[kind] = {"p50_change_pct": round(100 * (pb["p50_s"] / pa["p50_s"] - 1), 1), "p95_change_pct": round(100 * (pb["p95_s"] / pa["p95_s"] - 1), 1),
                           "errors_added": pb["errors"] - pa["errors"]}
    return delta


async def main_async(args) -> dict:
    audio = Path(args.stt_audio).read_bytes() if args.stt_audio else b"RIFF0000WAVE"
    embedder = make_embedder(args.embed, args.embed_threads)
    report = {"seconds_per_phase": args.seconds, "embed": args.embed, "embed_threads": args.embed_threads, "cpus": os.cpu_count(),
              "targets": {"stt": args.stt_url, "chat": args.chat_url}}
    report["A_foreground_only"] = await run_phase("A", args, audio, embedder, True, False)
    report["B_foreground_plus_indexing"] = await run_phase("B", args, audio, embedder, True, True)
    report["C_indexing_only"] = await run_phase("C", args, audio, embedder, False, True)
    report["change_from_A_to_B"] = compare(report["A_foreground_only"], report["B_foreground_plus_indexing"])
    report["indexing_throughput_with_and_without_foreground"] = {
        "with": report["B_foreground_plus_indexing"]["indexing"]["items_per_s"], "alone": report["C_indexing_only"]["indexing"]["items_per_s"]}
    return report


class _Stub(BaseHTTPRequestHandler):
    delay = 0.05

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        time.sleep(self.delay)
        body = json.dumps({"segments": [], "usage": {"completion_tokens": 20}, "choices": [{"message": {"content": "ok"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start_stub(delay: float) -> tuple[ThreadingHTTPServer, str]:
    handler = type("H", (_Stub,), {"delay": delay})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stt-url")
    p.add_argument("--stt-audio")
    p.add_argument("--stt-field", default="file")
    p.add_argument("--stt-token")
    p.add_argument("--chat-url")
    p.add_argument("--chat-model", default="reachy-local")
    p.add_argument("--chat-max-tokens", type=int, default=64)
    p.add_argument("--embed", choices=("minilm", "burn"), default="minilm")
    p.add_argument("--embed-threads", type=int, default=2)
    p.add_argument("--seconds", type=float, default=60)
    p.add_argument("--confirm-owner-approved", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    servers = []
    if args.self_test:
        stt, args.stt_url = start_stub(0.05)
        chat, args.chat_url = start_stub(0.08)
        servers = [stt, chat]
        args.embed, args.seconds = "burn", min(args.seconds, 3)
    elif not (args.stt_url and args.chat_url):
        print("give --stt-url and --chat-url (or --self-test)", file=sys.stderr)
        return 2
    elif not args.confirm_owner_approved:
        print(f"this would send requests to {args.stt_url} and {args.chat_url} for {3 * args.seconds:.0f} s and compete with real use; "
              "re-run with --confirm-owner-approved once the owner has agreed", file=sys.stderr)
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
