"""How much does building the index disturb the process around it? (Phase 44B gate: embedding load.)

Embeds a synthetic corpus the way the worker does (real all-MiniLM-L6-v2, batches of 16 in a worker thread) while a stand-in for the
foreground path ticks every 10 ms, and reports throughput and the worst event-loop stall with and without the indexing running. The
stall is what a chat or voice request handled by the same process would feel. This does not measure CPU contention with the speech,
language or diarization services on the homelab; that needs a deployment and is a separate, owner-approved check.

    python indexing_load.py [--segments 400] [--torch-threads N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


async def ticker(stop: asyncio.Event, interval: float = 0.01) -> list[float]:
    lags = []
    last = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(interval)
        now = time.perf_counter()
        lags.append(now - last - interval)
        last = now
    return lags


async def embed_all(texts: list[str]) -> float:
    from companion_core.rag.embeddings import embed

    started = time.perf_counter()
    for start in range(0, len(texts), 16):
        await asyncio.to_thread(embed, texts[start : start + 16])
        await asyncio.sleep(0)
    return time.perf_counter() - started


async def main(segments: int, torch_threads: int | None) -> dict:
    import torch
    from companion_core.rag.embeddings import embed

    if torch_threads:
        torch.set_num_threads(torch_threads)
    embed(["warm up the model"])  # load once; the first call includes the model load
    texts = [f"{['Priya', 'Tomas', 'Dana'][i % 3]}: we discussed topic {i} and the retry limit of five for the queue" for i in range(segments)]

    stop = asyncio.Event()
    quiet = asyncio.create_task(ticker(stop))
    await asyncio.sleep(1.0)
    stop.set()
    baseline = await quiet

    stop = asyncio.Event()
    busy = asyncio.create_task(ticker(stop))
    elapsed = await embed_all(texts)
    stop.set()
    during = await busy

    def summary(lags: list[float]) -> dict:
        ms = sorted(x * 1000 for x in lags)
        return {"ticks": len(ms), "median_ms": round(statistics.median(ms), 2), "p99_ms": round(ms[int(len(ms) * 0.99) - 1], 2), "max_ms": round(ms[-1], 2)}

    return {
        "segments": segments, "seconds": round(elapsed, 2), "segments_per_second": round(segments / elapsed, 1),
        "event_loop_stall_idle": summary(baseline), "event_loop_stall_while_embedding": summary(during),
        "cpus": os.cpu_count(), "torch_threads": __import__("torch").get_num_threads(), "load_average": list(os.getloadavg()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--segments", type=int, default=400)
    parser.add_argument("--torch-threads", type=int)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main(args.segments, args.torch_threads)), indent=2))
